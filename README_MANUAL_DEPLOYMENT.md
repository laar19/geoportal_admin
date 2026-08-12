# Manual Deployment Guide: Geoportal Admin Center

This guide details instructions for manually deploying **Geoportal Admin Center** directly onto a Linux Virtual Machine (Debian 12 / Ubuntu 22.04+) without Docker.

---

## 📋 Prerequisites

- **OS**: Debian 12 / Ubuntu 22.04 LTS
- **Python**: Version 3.10+
- **Keycloak Server**: Running Keycloak instance (e.g. `http://10.10.100.109:8085`)
- **FastAPI Backend**: Running Geoportal Backend (e.g. `http://10.10.100.126:8005/api/v1`)

---

## 🛠️ Step-by-Step Installation

```bash
cd /opt/geoportal_admin
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment Setup (`.env`)
```env
SECRET_KEY=adminsecretkey
BACKEND_PUBLIC_URL=http://10.10.100.126:8005/api/v1
GEOSERVER_PUBLIC_URL=http://10.10.100.126:8870/geoserver
LOGIN=True

ENABLE_KEYCLOAK_AUTH=True
KEYCLOAK_SERVER_URL=http://10.10.100.109:8085
KEYCLOAK_REALM=my-app
KEYCLOAK_CLIENT_ID=my-web-app
KEYCLOAK_CLIENT_SECRET=a-super-secret-value
KEYCLOAK_REDIRECT_URI=http://10.10.100.126:3001/callback
```

### Systemd Service Setup (`/etc/systemd/system/geoportal-admin.service`)
```ini
[Unit]
Description=Geoportal Admin Center Service
After=network.target

[Service]
User=root
WorkingDirectory=/opt/geoportal_admin
ExecStart=/opt/geoportal_admin/venv/bin/gunicorn --bind 0.0.0.0:3001 --workers 3 app:app
Restart=always
RestartSec=5
EnvironmentFile=/opt/geoportal_admin/.env

[Install]
WantedBy=multi-user.target
```

Enable and start service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable geoportal-admin
sudo systemctl start geoportal-admin
```
