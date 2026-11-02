#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_ROOT="$APP_ROOT/deployment"
SERVICE_SOURCE="$DEPLOY_ROOT/face_ai_service"
MODEL_SOURCE="$DEPLOY_ROOT/models/face_detection_yunet_2023mar.onnx"
APP_DIR="/opt/ff-face-ai"
ETC_DIR="/etc/ff-face-ai"
DATA_DIR="/var/lib/ff-face-ai"
ENV_FILE="$ETC_DIR/face-ai.env"
SERVICE_USER="ff-face-ai"

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || fail "Run once on the Odoo server as root, for example: sudo bash deployment/install-local-face-service.sh"
[[ -f "$SERVICE_SOURCE/pyproject.toml" && -f "$MODEL_SOURCE" ]] || fail "The bundled face-service files are missing. Re-download the complete Face Attendance addon package."
command -v systemctl >/dev/null || fail "This installer supports Ubuntu Linux with systemd only."
[[ -r /etc/os-release ]] || fail "Cannot detect the Linux distribution."
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" =~ ^(22\.04|24\.04)$ ]] || fail "Supported hosts are Ubuntu 22.04 and 24.04 with Odoo installed on this same host. Odoo.sh, Odoo Online, containers, and other distributions need a different deployment profile."
[[ ! -e "$ENV_FILE" ]] || fail "The face service is already installed. This installer never replaces existing gallery encryption keys. Contact the system administrator for an upgrade procedure."

EXPECTED_MODEL_SHA="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
ACTUAL_MODEL_SHA="$(sha256sum "$MODEL_SOURCE" | cut -d ' ' -f 1)"
[[ "$ACTUAL_MODEL_SHA" == "$EXPECTED_MODEL_SHA" ]] || fail "The bundled YuNet model checksum does not match the release manifest."

echo "Installing the private face service on this Odoo host. This can take several minutes."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl openssl python3 python3-venv python3-pip
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required.")
PY

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR" "$APP_DIR/models" "$DATA_DIR"
install -d -o root -g "$SERVICE_USER" -m 0750 "$ETC_DIR"
cp -a "$SERVICE_SOURCE/." "$APP_DIR/"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0640 "$MODEL_SOURCE" "$APP_DIR/models/face_detection_yunet_2023mar.onnx"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install "$APP_DIR[pilot]"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR" "$DATA_DIR"

openssl req -x509 -nodes -days 1825 -newkey rsa:3072 \
    -keyout "$ETC_DIR/server.key" -out "$ETC_DIR/server.crt" \
    -subj "/CN=localhost" -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" >/dev/null 2>&1
chown root:"$SERVICE_USER" "$ETC_DIR/server.key" "$ETC_DIR/server.crt"
chmod 0640 "$ETC_DIR/server.key"
chmod 0644 "$ETC_DIR/server.crt"

PAIR_CODE="$("$APP_DIR/.venv/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
)"
"$APP_DIR/.venv/bin/python" - "$ENV_FILE" "$DATA_DIR" "$ETC_DIR" "$APP_DIR" <<'PY'
import os
import secrets
import sys
from cryptography.fernet import Fernet

env_path, data_dir, etc_dir, app_dir = sys.argv[1:]
values = {
    "FF_LISTEN_HOST": "127.0.0.1",
    "FF_LISTEN_PORT": "8787",
    "FF_MAX_CAPTURE_BYTES": "2000000",
    "FF_ODOO_SHARED_SECRET": secrets.token_urlsafe(48),
    "FF_RESULT_HMAC_SECRET": secrets.token_urlsafe(48),
    "FF_PILOT_ENABLED": "true",
    "FF_PILOT_ADMIN_TOKEN": secrets.token_urlsafe(48),
    "FF_PILOT_GALLERY_DIR": f"{data_dir}/pilot-gallery",
    "FF_PILOT_GALLERY_KEYS": Fernet.generate_key().decode("ascii"),
    "FF_NONCE_DB_PATH": f"{data_dir}/nonces.sqlite3",
    "FF_PILOT_DETECTOR_PATH": f"{app_dir}/models/face_detection_yunet_2023mar.onnx",
    "FF_PILOT_THRESHOLD": "70",
    "FF_TLS_CERTFILE": f"{etc_dir}/server.crt",
    "FF_TLS_KEYFILE": f"{etc_dir}/server.key",
    "FF_SETUP_PAIR_CODE_FILE": f"{data_dir}/setup-code",
    "FF_SETUP_PAIRED_PATH": f"{data_dir}/setup-paired",
}
fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    for key, value in values.items():
        stream.write(f"{key}={value}\n")
PY
PAIR_FILE="$DATA_DIR/setup-code"
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0600 /dev/null "$PAIR_FILE"
printf '%s\n' "$PAIR_CODE" > "$PAIR_FILE"
chmod 0600 "$ENV_FILE"
chown root:root "$ENV_FILE"

cat > /etc/systemd/system/ff-face-ai.service <<UNIT
[Unit]
Description=Flous Flow local face-attendance service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python -m ff_face_ai_service.server
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR
MemoryMax=1G
CPUQuota=150%
TasksMax=64
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
chmod 0644 /etc/systemd/system/ff-face-ai.service
systemctl daemon-reload
systemctl enable --now ff-face-ai.service

READY=false
for _ in $(seq 1 45); do
    if curl --silent --show-error --insecure --fail https://127.0.0.1:8787/health/ready >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 2
done
[[ "$READY" == true ]] || {
    journalctl -u ff-face-ai.service -n 30 --no-pager >&2 || true
    fail "The face service did not become ready. No Odoo policy was enabled. Ask the server administrator to review the service log."
}

echo
echo "Face service is ready and bound to localhost only."
echo "In Odoo, open Face Attendance > Connect Face Service and enter this one-time setup code:"
echo "$PAIR_CODE"
echo "The code is also stored with root-only access at $PAIR_FILE and is deleted after successful pairing."
echo "Biometric attendance remains disabled until an HR manager enables the company policy."
