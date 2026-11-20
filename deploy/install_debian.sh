#!/usr/bin/env bash
set -euo pipefail

# Script de referencia para instalar Net-Tool (Worker + Streamlit) en Debian
# Ejecutar como root o con sudo: sudo bash deploy/install_debian.sh

INSTALL_DIR="/opt/net-tool"
SERVICE_USER="netmonitor"

echo "==> Instalando paquetes base en Debian..."
apt-get update
apt-get install -y python3 python3-venv python3-pip postgresql mtr-tiny iputils-ping

echo "==> Creando usuario del sistema ($SERVICE_USER)..."
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

echo "==> Copiando proyecto a $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r app deploy requirements.txt config.example.json "$INSTALL_DIR/"

if [ ! -f "$INSTALL_DIR/config.json" ]; then
  cp "$INSTALL_DIR/config.example.json" "$INSTALL_DIR/config.json"
  echo "IMPORTANTE: Edita $INSTALL_DIR/config.json con tu clave de PostgreSQL e IPs de California."
fi

echo "==> Creando entorno virtual e instalando dependencias Python..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "==> Instalando servicios systemd..."
cp "$INSTALL_DIR/deploy/net-monitor-worker.service" /etc/systemd/system/net-monitor-worker.service
cp "$INSTALL_DIR/deploy/net-monitor-web.service" /etc/systemd/system/net-monitor-web.service
systemctl daemon-reload
systemctl enable net-monitor-worker.service net-monitor-web.service

echo ""
echo "Listo. Pasos siguientes:"
echo "1. Crea el usuario y base de datos en PostgreSQL (ver README.md)."
echo "2. Edita $INSTALL_DIR/config.json con el DSN de PostgreSQL y tus destinos."
echo "3. Inicializa tablas: sudo -u $SERVICE_USER $INSTALL_DIR/.venv/bin/python -m app.main --config $INSTALL_DIR/config.json --init-db"
echo "4. Inicia ambos servicios: sudo systemctl start net-monitor-worker net-monitor-web"
