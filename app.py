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
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "geoportal-admin")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "admin-panel")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "admin-panel-secret")
KEYCLOAK_REDIRECT_URI = os.getenv("KEYCLOAK_REDIRECT_URI")

# PostGIS Database Credentials for Size Calculations
POSTGIS_HOST = os.getenv("POSTGIS_HOST", "10.10.100.194")
POSTGIS_PORT = os.getenv("POSTGIS_PORT", "5432")
POSTGIS_DB = os.getenv("POSTGIS_DB", "geoportal_db")
POSTGIS_USER = os.getenv("POSTGIS_USER", "geoportal_user")
POSTGIS_PASSWORD = os.getenv("POSTGIS_PASSWORD", "geoportal_pass")

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

def get_total_layers_size():
    """Queries PostGIS via SQLAlchemy engine for total size of vector tables in vectors schema"""
    from sqlalchemy import create_engine, text
    try:
        db_url = f"postgresql://{POSTGIS_USER}:{POSTGIS_PASSWORD}@{POSTGIS_HOST}:{POSTGIS_PORT}/{POSTGIS_DB}"
        engine = create_engine(db_url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            res = conn.execute(text("""
                SELECT COALESCE(SUM(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))), 0)
                FROM information_schema.tables 
                WHERE table_schema = 'vectors';
            """)).scalar()
            return int(res or 0)
    except Exception as e:
        print(f"PostGIS Size Error: {e}")
        return 0

def format_size(size_bytes):
    """Formats bytes to KB, MB, or GB automatically"""
    if size_bytes >= 1073741824:
        return f"{size_bytes / 1073741824:.2f} GB"
    elif size_bytes >= 1048576:
        return f"{size_bytes / 1048576:.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"

def get_layer_health():
    """Checks WMS health for published layers in GeoServer"""
    try:
        r = requests.get(f"{GEOSERVER_PUBLIC_URL}/rest/layers.json", 
                         auth=('admin', os.getenv("GEOSERVER_ADMIN_PASSWORD", "geoserver")), 
                         timeout=3)
        if r.status_code != 200:
            return 0, 0, 0
        layers_data = r.json().get("layers", {})
        if not layers_data or "layer" not in layers_data:
            return 0, 0, 100
        layers_list = layers_data.get("layer", [])
        if isinstance(layers_list, dict):
            layers_list = [layers_list]
        total = len(layers_list)
        if total == 0:
            return 0, 0, 100
        healthy = 0
        for layer in layers_list:
            name = layer.get("name", "")
            try:
                wms_r = requests.get(
                    f"{GEOSERVER_PUBLIC_URL}/wms?service=WMS&request=GetMap&layers={name}&bbox=-180,-90,180,90&width=1&height=1&srs=EPSG:4326&format=image/png",
                    timeout=2
                )
                if wms_r.status_code == 200:
                    healthy += 1
            except Exception:
                pass
        pct = int((healthy / total) * 100) if total > 0 else 100
        return healthy, total, pct
    except Exception as e:
        print(f"Layer Health Error: {e}")
        return 0, 0, 0

def get_user_count():
    """Queries Keycloak Admin API for total user count in application realm (my-app)"""
    try:
        token_r = requests.post(
            f"{KEYCLOAK_SERVER_URL}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli",
                  "username": "admin", "password": "admin"},
            timeout=3
        )
        if token_r.status_code != 200:
            return 0
        token = token_r.json().get("access_token")
        count_r = requests.get(
            f"{KEYCLOAK_SERVER_URL}/admin/realms/my-app/users/count",
            headers={"Authorization": f"Bearer {token}"},
            timeout=3
        )
        return count_r.json() if count_r.status_code == 200 else 0
    except Exception as e:
        print(f"User Count Error: {e}")
        return 0

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

    size_bytes = get_total_layers_size()
    size_formatted = format_size(size_bytes)
    healthy_layers, total_gs_layers, layer_health_pct = get_layer_health()
    user_count = get_user_count()

    return {
        "db_connected": db_ok,
        "geoserver_connected": gs_ok,
        "total_layers": layers_count,
        "uptime": uptime_str,
        "backend_url": BACKEND_PUBLIC_URL,
        "geoserver_url": GEOSERVER_PUBLIC_URL,
        "total_size_bytes": size_bytes,
        "total_size_formatted": size_formatted,
        "healthy_layers": healthy_layers,
        "total_gs_layers": total_gs_layers,
        "layer_health_pct": layer_health_pct,
        "user_count": user_count
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
