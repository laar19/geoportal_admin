# Geoportal Admin Center (`geoportal_admin`)

An administrative dashboard and analytics portal for the **Geoportal Platform**. Built with **Flask**, **Keycloak OIDC**, and a modern glassmorphic UI.

---

## 🏛️ Key Features

- **Keycloak OIDC Authentication**: Authenticates administrators against Keycloak (`10.10.100.109:8085`, `my-app` realm).
- **Analytics & Infrastructure Health Metrics**: Real-time monitoring of PostGIS database connection status, GeoServer WMS engine health, total published vector layers, and admin uptime.
- **Layer Management**: Browse, search, filter, download GeoJSON, and manage spatial vector layers stored in the PostGIS `vectors` schema.
- **Shapefile Ingestion**: Upload multi-part Shapefiles (`.shp`, `.shx`, `.dbf`, `.prj`) directly to the backend for automated PostGIS insertion and GeoServer publishing.

---

## 🚀 Quick Start (Docker)

```bash
cp .env.example .env
docker compose up --build -d
```

Access Admin Center at: `http://localhost:3001`
