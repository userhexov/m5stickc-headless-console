#!/usr/bin/env bash
# Erase the board and flash a MicroPython image at 0x1000.
set -euo pipefail

PORT="${ESP32_PORT:-/dev/ttyUSB0}"
BAUD="${ESP32_BAUD:-115200}"
FW="${1:-}"

if [[ -z "$FW" || ! -f "$FW" ]]; then
  echo "usage: $0 /path/to/ESP32_GENERIC-*.bin" >&2
  exit 1
fi

echo "[!] This ERASES the entire flash on $PORT."
read -r -p "continue? [y/N] " ans
[[ "$ans" == "y" || "$ans" == "Y" ]] || exit 1

systemctl --user stop esp32-dashboard 2>/dev/null || true

uvx --from esptool esptool --port "$PORT" --baud "$BAUD" erase-flash
uvx --from esptool esptool --port "$PORT" --baud "$BAUD" write-flash 0x1000 "$FW"

echo "[ok] flashed $FW"
