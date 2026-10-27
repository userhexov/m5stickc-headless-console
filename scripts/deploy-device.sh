#!/usr/bin/env bash
# Upload the MicroPython shell to the board.
# If the dashboard is running it is asked to release the UART first.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${ESP32_PORT:-/dev/ttyUSB0}"
DASH="${ESP32_DASH:-http://127.0.0.1:8770}"

pause() {
  curl -sf -X POST "$DASH/api/pause" \
    -H 'Content-Type: application/json' -d '{"seconds":60}' >/dev/null 2>&1 || true
}
resume() {
  curl -sf -X POST "$DASH/api/resume" \
    -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1 || true
}

trap resume EXIT
pause

uvx mpremote connect "$PORT" cp "$ROOT/firmware/stick.py" :stick.py
uvx mpremote connect "$PORT" cp "$ROOT/firmware/main.py" :main.py
uvx mpremote connect "$PORT" reset || true

echo "[ok] firmware uploaded; shell starts on boot"
