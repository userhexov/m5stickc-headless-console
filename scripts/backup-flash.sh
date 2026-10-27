#!/usr/bin/env bash
# Make a full flash backup before doing anything destructive.
set -euo pipefail

PORT="${ESP32_PORT:-/dev/ttyUSB0}"
BAUD="${ESP32_BAUD:-115200}"
SIZE="${FLASH_SIZE:-4MB}"
OUT="${1:-$HOME/esp32-backup/m5stick-full-${SIZE}.bin}"

mkdir -p "$(dirname "$OUT")"
systemctl --user stop esp32-dashboard 2>/dev/null || true

uvx --from esptool esptool --port "$PORT" --baud "$BAUD" read-flash 0 "$SIZE" "$OUT"
sha256sum "$OUT"

echo "[ok] backup: $OUT"
echo "[i] restore with: $0-restore.sh $OUT"
