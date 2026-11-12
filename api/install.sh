#!/usr/bin/env bash
#
# Instalación de la API de ytpremiun-vip en Ubuntu 22.04/24.04.
# Ejecutar como root:  bash api/install.sh
#
# Variables opcionales:
#   PORT=3000 APP_DIR=/opt/ytpremiun DATA_DIR=/var/lib/ytpremiun

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ytpremiun}"
DATA_DIR="${DATA_DIR:-/var/lib/ytpremiun}"
ENV_FILE="${ENV_FILE:-/etc/ytpremiun-api.env}"
SERVICE_NAME="ytpremiun-api"
PORT="${PORT:-3000}"
USER_NAME="ytpremiun"
REPO_URL="${REPO_URL:-https://github.com/natsu-dev01/ytpremiun_vip.git}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Ejecuta este script como root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Instalando dependencias del sistema"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git ffmpeg

NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node -p "process.versions.node.split('.')[0]")"
fi
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "==> Instalando Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y -qq nodejs
fi
echo "==> Node $(node --version), ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f1-3)"

echo "==> Preparando usuario y directorios"
if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$USER_NAME"
fi
mkdir -p "$DATA_DIR/jobs"
chown -R "$USER_NAME:$USER_NAME" "$DATA_DIR"
chmod 750 "$DATA_DIR"

echo "==> Obteniendo el código"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

echo "==> Configuración"
if [ ! -f "$ENV_FILE" ]; then
  API_KEY="$(node -e "console.log(require('crypto').randomBytes(32).toString('hex'))")"
  cat > "$ENV_FILE" <<EOF
PORT=$PORT
HOST=0.0.0.0
API_KEY=$API_KEY
DATA_DIR=$DATA_DIR
MAX_CONCURRENT=1
MAX_QUEUE=20
JOB_TTL_HOURS=12
MAX_STORAGE_GB=12
DEFAULT_CONNECTIONS=6
EOF
  chmod 600 "$ENV_FILE"
  echo
  echo "API key generada (guárdala): $API_KEY"
  echo
else
  echo "Conservando la configuración existente: $ENV_FILE"
fi

echo "==> Instalando servicio systemd"
install -m 644 "$APP_DIR/api/ytpremiun-api.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  echo "==> Abriendo el puerto $PORT en ufw"
  ufw allow "$PORT/tcp" >/dev/null || true
fi

sleep 2
systemctl --no-pager --full status "$SERVICE_NAME" | head -20 || true
echo
echo "==> Comprobación local"
curl -fsS "http://127.0.0.1:$PORT/health" && echo
