#!/usr/bin/env bash
# Install the presence-lock watcher as a systemd --user service (not started).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/esp32-presence.service"

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=M5StickC presence lock (idle -> hyprlock)
After=esp32-dashboard.service

[Service]
WorkingDirectory=$ROOT
ExecStart=/usr/bin/env python3 $ROOT/scripts/presence_lock.py
Restart=always
RestartSec=3
Environment=ESP32_DASH=http://127.0.0.1:8770
Environment=IDLE_SECONDS=${IDLE_SECONDS:-300}
Environment=LOCK_CMD=${LOCK_CMD:-hyprlock}

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
echo "[ok] installed $UNIT"
echo "     enable: systemctl --user enable --now esp32-presence"
echo "     logs:   journalctl --user -u esp32-presence -f"
