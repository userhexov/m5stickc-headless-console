#!/usr/bin/env bash
# Restore a full flash dump (e.g. the original Bruce firmware).
set -euo pipefail

PORT="${ESP32_PORT:-/dev/ttyUSB0}"
BAUD="${ESP32_BAUD:-115200}"
BACKUP="${1:-$HOME/esp32-backup/m5stick-full-4MB.bin}"

if [[ ! -f "$BACKUP" ]]; then
  echo "backup not found: $BACKUP" >&2
  exit 1
fi

systemctl --user stop esp32-dashboard 2>/dev/null || true

uvx --from esptool esptool --port "$PORT" --baud "$BAUD" write-flash 0 "$BACKUP"

echo "[ok] restored $BACKUP"
