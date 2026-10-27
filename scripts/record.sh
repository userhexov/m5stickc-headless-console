#!/usr/bin/env bash
# Record IMU to CSV and print the summary.
set -euo pipefail

DASH="${ESP32_DASH:-http://127.0.0.1:8770}"
SECS="${1:-10}"

curl -sf -X POST "$DASH/api/record" \
  -H 'Content-Type: application/json' \
  -d "{\"seconds\":$SECS}" | python3 -m json.tool
