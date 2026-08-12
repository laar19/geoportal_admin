import os
import time
import subprocess
import requests
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "geoportal-admin-secret-key")

# Configuration
BACKEND_PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", "http://10.10.100.245:8000/api/v1")
BACKEND_INTERNAL_URL = os.getenv("BACKEND_URL", "http://10.10.100.245:8000") + "/api/v1"
GEOSERVER_PUBLIC_URL = os.getenv("GEOSERVER_PUBLIC_URL", "http://10.10.100.161:8080/geoserver")
GEOSERVER_INTERNAL_URL = os.getenv("GEOSERVER_URL", "http://10.10.100.161:8080")
LOGIN_ENABLED = os.getenv("LOGIN", "True").lower() == "true"

# Keycloak OIDC Configuration
ENABLE_KEYCLOAK_AUTH = os.getenv("ENABLE_KEYCLOAK_AUTH", "True").lower() == "true"
KEYCLOAK_SERVER_URL = os.getenv("KEYCLOAK_SERVER_URL", "http://10.10.100.109:8085")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "my-app")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "my-web-app")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "a-super-secret-value")
KEYCLOAK_REDIRECT_URI = os.getenv("KEYCLOAK_REDIRECT_URI")

# Distributed VM Service IPs for Log Monitoring
VM_SERVICE_IPS = {
    "backend": os.getenv("VM_BACKEND_IP", "10.10.100.245"),
    "frontend": os.getenv("VM_FRONTEND_IP", "10.10.100.167"),
    "geoserver": os.getenv("VM_GEOSERVER_IP", "10.10.100.161"),
    "admin": os.getenv("VM_ADMIN_IP", "127.0.0.1"),
}

START_TIME = time.time()

# Flask-Login Setup
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id, email, name=None):
        self.id = id
        self.email = email
        self.name = name or email

@login_manager.user_loader
def load_user(user_id):
    user_data = session.get("user_data")
    if user_data and user_data.get("id") == user_id:
        return User(user_data["id"], user_data["email"], user_data.get("name"))
    if user_id == "1":
        return User("1", "admin@geoportal.com", "Admin")
    return None

def login_required_if_enabled(f):
    @wraps(f)
    def decorated_view(*args, **kwargs):
        if LOGIN_ENABLED and not current_user.is_authenticated:
            return login_manager.unauthorized()
        return f(*args, **kwargs)
    return decorated_view

def get_system_metrics():
    db_ok = False
    gs_ok = False
    layers_count = 0

    # Backend & DB Check
    try:
        r = requests.get(f"{BACKEND_PUBLIC_URL}/health", timeout=3)
        if r.status_code == 200:
            db_ok = r.json().get("db_connected", False)
    except Exception as e:
        print(f"Backend Health Error: {e}")

    # Layers Count
    try:
        r = requests.get(f"{BACKEND_PUBLIC_URL}/layers/search?per_page=1000", timeout=3)
        if r.status_code == 200:
            layers_count = r.json().get("total", 0)
    except Exception:
        pass

    # GeoServer Check
    try:
        r = requests.get(f"{GEOSERVER_PUBLIC_URL}/rest/about/version.xml", 
                         auth=('admin', os.getenv("GEOSERVER_ADMIN_PASSWORD", "geoserver")), 
                         timeout=3)
        gs_ok = r.status_code == 200
    except Exception:
        gs_ok = False

    uptime_seconds = int(time.time() - START_TIME)
    uptime_str = f"{uptime_seconds // 3600}h {(uptime_seconds % 3600) // 60}m {uptime_seconds % 60}s"

    return {
        "db_connected": db_ok,
        "geoserver_connected": gs_ok,
        "total_layers": layers_count,
        "uptime": uptime_str,
        "backend_url": BACKEND_PUBLIC_URL,
        "geoserver_url": GEOSERVER_PUBLIC_URL
    }

def fetch_remote_logs(service_name, lines=50):
    """Fetch logs from target application microservice via SSH or Systemd journal"""
    if service_name == "admin":
        cmd = f"journalctl -u geoportal-admin.service -n {lines} --no-pager"
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
            return res.stdout or res.stderr or f"[INFO] Admin service running natively."
        except Exception as e:
            return f"[ERROR] Failed to read admin logs: {e}"

    target_ip = VM_SERVICE_IPS.get(service_name)
    if not target_ip:
        return f"[WARN] Unknown microservice: {service_name}"

    service_units = {
        "backend": "geoportal-backend.service",
        "frontend": "geoportal-frontend.service",
        "geoserver": "geoserver.service",
    }
    unit = service_units.get(service_name, f"{service_name}.service")
    
    ssh_cmd = f"sshpass -p 'root' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 root@{target_ip} 'journalctl -u {unit} -n {lines} --no-pager 2>/dev/null || tail -n {lines} /var/log/messages 2>/dev/null'"
    
    try:
        res = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=5)
        output = res.stdout.strip()
        if not output:
            output = f"[INFO] Service {service_name} on {target_ip} is active. (No recent systemd error logs)"
        return output
    except Exception as e:
        return f"[WARN] Unable to reach microservice log host {target_ip}: {str(e)}"

@app.route("/login", methods=["GET", "POST"])
def login():
    if not LOGIN_ENABLED:
        return redirect(url_for('index'))
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if ENABLE_KEYCLOAK_AUTH:
        redirect_uri = KEYCLOAK_REDIRECT_URI or (request.host_url.rstrip('/') + url_for('callback'))
        kc_auth_url = (
            f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
            f"?client_id={KEYCLOAK_CLIENT_ID}"
            f"&response_type=code"
            f"&scope=openid+email+profile"
            f"&redirect_uri={redirect_uri}"
        )
        return redirect(kc_auth_url)
        
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if email == "admin@geoportal.com" and password == "admin":
            user = User("1", email, "Admin")
            session["user_data"] = {"id": "1", "email": email, "name": "Admin"}
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash("Invalid credentials", "error")
            
    return render_template("login.html")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Authorization code missing", "error")
        return redirect(url_for("login"))

    redirect_uri = KEYCLOAK_REDIRECT_URI or (request.host_url.rstrip('/') + url_for('callback'))
    token_url = f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    
    try:
        token_res = requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        if token_res.status_code != 200:
            flash(f"Keycloak token error: {token_res.text}", "error")
            return redirect(url_for("login"))

        tokens = token_res.json()
        access_token = tokens.get("access_token")
        id_token = tokens.get("id_token")

        userinfo_url = f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo"
        userinfo_res = requests.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        user_info = userinfo_res.json() if userinfo_res.status_code == 200 else {}

        user_id = user_info.get("sub") or "admin-user"
        email = user_info.get("email") or user_info.get("preferred_username") or "admin@geoportal.com"
        name = user_info.get("name") or user_info.get("preferred_username") or email

        user = User(user_id, email, name)
        session["user_data"] = {"id": user_id, "email": email, "name": name}
        session["access_token"] = access_token
        session["id_token"] = id_token
        login_user(user)

        return redirect(url_for("index"))

    except Exception as e:
        flash(f"Authentication error: {str(e)}", "error")
        return redirect(url_for("login"))

@app.route("/logout")
@login_required
def logout():
    id_token = session.get("id_token")
    logout_user()
    session.clear()
    if ENABLE_KEYCLOAK_AUTH:
        post_logout = request.host_url.rstrip('/') + url_for('login')
        kc_logout_url = (
            f"{KEYCLOAK_SERVER_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/logout"
            f"?post_logout_redirect_uri={post_logout}"
            f"&client_id={KEYCLOAK_CLIENT_ID}"
        )
        if id_token:
            kc_logout_url += f"&id_token_hint={id_token}"
        return redirect(kc_logout_url)
    return redirect(url_for('login'))

@app.route("/api/admin/metrics")
@login_required_if_enabled
def api_metrics():
    return jsonify(get_system_metrics())

@app.route("/api/admin/logs")
@login_required_if_enabled
def api_logs():
    service = request.args.get("service", "all")
    lines = int(request.args.get("lines", 50))
    
    if service == "all":
        results = {}
        for s in ["backend", "frontend", "geoserver", "admin"]:
            results[s] = fetch_remote_logs(s, lines=20)
        return jsonify({"status": "ok", "logs": results})
    else:
        log_text = fetch_remote_logs(service, lines=lines)
        return jsonify({"status": "ok", "service": service, "logs": log_text})

@app.route("/")
@login_required_if_enabled
def index():
    metrics = get_system_metrics()
    return render_template("index.html", 
                         metrics=metrics,
                         backend_url=BACKEND_PUBLIC_URL,
                         geoserver_url=GEOSERVER_PUBLIC_URL,
                         LOGIN_ENABLED=LOGIN_ENABLED)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3001)
