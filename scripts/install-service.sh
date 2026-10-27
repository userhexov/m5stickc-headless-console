#!/usr/bin/env bash
# Install and start the dashboard as a systemd --user service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/esp32-dashboard.service"

mkdir -p "$UNIT_DIR"

cat > "$UNIT" <<EOF
[Unit]
Description=M5StickC headless web dashboard
After=default.target

[Service]
WorkingDirectory=$ROOT
ExecStart=/usr/bin/env uv run --quiet --with pyserial python $ROOT/dashboard/server.py
Restart=always
RestartSec=3
Environment=ESP32_PORT=${ESP32_PORT:-/dev/ttyUSB0}

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now esp32-dashboard.service
sleep 1
systemctl --user --no-pager status esp32-dashboard.service | head -12
echo "[ok] http://127.0.0.1:${DASH_PORT:-8770}"
