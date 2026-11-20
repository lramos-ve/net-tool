# Net-Tool · Monitor CCTV & Conectividad (Debian + PostgreSQL + Streamlit)

Servicio de monitoreo continuo para diagnosticar fallos nocturnos de conectividad (LAN, ISPs locales, salida internacional, puertos iVMS/RTSP hacia California y DNS), con almacenamiento histórico en **PostgreSQL** y dashboard web en **Streamlit**.

> Nota: La versión original interactiva de consola se conserva intacta en la rama `main`.

## Características

- **Ping con métricas reales**: latencia mín/prom/máx, jitter (`mdev`) y `%` de pérdida de paquetes.
- **Pruebas TCP para CCTV / iVMS**: verifica apertura y tiempo de conexión a puertos como `8000` (SDK), `554` (RTSP) o `443`.
- **Pruebas DNS**: mide resolución y tiempo de respuesta de dominios/DDNS.
- **Trazas de ruta automáticas (`mtr` / `traceroute`)**: cuando un enlace o puerto se degrada o cae, captura la ruta exacta del incidente (con cooldown configurable).
- **Dashboard Streamlit**: filtros rápidos (*Última noche*, *6h*, *24h*, *7 días*, rango personalizado), gráficas comparativas de latencia/jitter/pérdida, bitácora de incidentes con visor de trazas y exportación a CSV.

## Instalación en Debian

### 1. Crear base de datos en PostgreSQL

```bash
sudo apt-get update && sudo apt-get install -y postgresql mtr-tiny iputils-ping python3-venv
sudo -u postgres psql -c "CREATE USER netmonitor WITH PASSWORD 'TU_CLAVE_SEGURA';"
sudo -u postgres psql -c "CREATE DATABASE net_monitor OWNER netmonitor;"
```

### 2. Instalar la aplicación y los servicios `systemd`

```bash
sudo bash deploy/install_debian.sh
```

Luego edita `/opt/net-tool/config.json`:
- Ajusta `database.dsn` con tu contraseña de PostgreSQL.
- Agrega tus IPs/dominios de **California** en `ping_targets` y habilita los puertos de iVMS/RTSP (`8000`, `554`, etc.) en `tcp_targets`.

Inicializa las tablas y arranca ambos servicios (recolector + dashboard Streamlit):

```bash
sudo -u netmonitor /opt/net-tool/.venv/bin/python -m app.main --config /opt/net-tool/config.json --init-db
sudo systemctl start net-monitor-worker net-monitor-web
sudo systemctl status net-monitor-worker net-monitor-web
```

Accede al dashboard Streamlit en `http://<IP-DEL-SERVIDOR>:8080`.

### Logs de los servicios

```bash
sudo journalctl -u net-monitor-worker -u net-monitor-web -f
```
