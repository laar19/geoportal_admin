# Manual Deployment Guide: Geoportal Admin Center

This guide details the manual step-by-step procedures for deploying the **Geoportal Admin Center** microservice on a Linux Virtual Machine without using Docker.

---

## 📋 Prerequisites

- **Python Manager**: `pyenv`
- **Keycloak Server**: Running Keycloak instance (e.g., `http://10.10.100.109:8085`)
- **FastAPI Backend**: Running Geoportal Backend (e.g., `http://10.10.100.245:8000/api/v1`)
- **PostGIS DB**: Connection details to PostGIS database


---

## 🛠️ Step 1: System Package Installation

Install build tools, Python compilation dependencies, and `sshpass` for remote log gathering:

```bash
sudo apt-get update && sudo apt-get install -y \
    build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev curl git libncursesw5-dev \
    xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev \
    sshpass
```

---

## 🐍 Step 2: Python Version Management with `pyenv`

1. Install `pyenv` using the automatic installer:
   ```bash
   curl https://pyenv.run | bash
   ```

2. Configure environment variables in `~/.bashrc`:
   ```bash
   echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
   echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
   echo 'eval "$(pyenv init - bash)"' >> ~/.bashrc
   echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
   ```

3. Apply shell environment changes immediately:
   ```bash
   source ~/.bashrc
   ```

4. Install Python 3.12.0 via `pyenv`:
   ```bash
   pyenv install 3.12.0
   ```

5. Set the local Python version in the application directory:
   ```bash
   cd /opt/geoportal_admin
   pyenv local 3.12.0
   ```

---

## 📦 Step 3: Virtual Environment & Dependencies with `uv`

1. Create the virtual environment:
   ```bash
   python -m venv .venv
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Install `uv` (Astral's blazingly fast Rust package manager):
   ```bash
   pip install uv
   ```

4. Install project dependencies using `uv`:
   ```bash
   uv pip install -r requirements.txt
   ```

---

## ⚙️ Step 4: Environment Configuration

Create the configuration file `/opt/geoportal_admin/.env`:

```env
SECRET_KEY=geoportal-admin-secret-key
BACKEND_PUBLIC_URL=http://10.10.100.245:8000/api/v1
GEOSERVER_PUBLIC_URL=http://10.10.100.161:8080/geoserver
LOGIN=True

# Keycloak OIDC Configuration (Independent Admin Realm)
ENABLE_KEYCLOAK_AUTH=True
KEYCLOAK_SERVER_URL=http://10.10.100.109:8085
KEYCLOAK_REALM=geoportal-admin
KEYCLOAK_CLIENT_ID=admin-panel
KEYCLOAK_CLIENT_SECRET=admin-panel-secret
KEYCLOAK_REDIRECT_URI=http://10.10.100.50:3001/callback

# Service IPs for Remote Microservice Systemd Logs
VM_BACKEND_IP=10.10.100.245
VM_FRONTEND_IP=10.10.100.167
VM_GEOSERVER_IP=10.10.100.161

# PostGIS Connection for Table Size Calculation
POSTGIS_HOST=10.10.100.194
POSTGIS_PORT=5432
POSTGIS_DB=geoportal_db
POSTGIS_USER=geoportal_user
POSTGIS_PASSWORD=geoportal_pass
```

---

## 🚀 Step 5: Production Systemd Service Configuration

Create `/etc/systemd/system/geoportal-admin.service`:

```ini
[Unit]
Description=Geoportal Admin Center Service
After=network.target

[Service]
User=root
WorkingDirectory=/opt/geoportal_admin
ExecStart=/opt/geoportal_admin/.venv/bin/gunicorn --bind 0.0.0.0:3001 --workers 3 app:app
Restart=always
RestartSec=5
EnvironmentFile=/opt/geoportal_admin/.env

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable geoportal-admin
sudo systemctl start geoportal-admin
sudo systemctl status geoportal-admin
```
