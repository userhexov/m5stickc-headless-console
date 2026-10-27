#!/usr/bin/env bash
# Show the three log layers: host events, device log, MCP audit.
set -euo pipefail

DASH="${ESP32_DASH:-http://127.0.0.1:8770}"
N="${1:-20}"
AUDIT="${ESP32_MCP_STATE:-$HOME/.local/state/esp32-mcp}/audit.jsonl"

echo "=== host events ($DASH) ==="
curl -sf "$DASH/api/logs?n=$N" | python3 -c '
import json, sys
for e in json.load(sys.stdin).get("entries", []):
    print("%s  %-7s %s" % (e.get("iso"), e.get("kind"), e.get("text")))
'

echo
echo "=== device log ==="
curl -sf "$DASH/api/device-log?n=$N" | python3 -c '
import json, sys
print(json.load(sys.stdin).get("output", ""))
'

echo
echo "=== mcp audit ($AUDIT) ==="
if [ -f "$AUDIT" ]; then
  tail -n "$N" "$AUDIT" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    print("%s  %-12s %5sms  %s  %s" % (e.get("iso"), e.get("tool"), e.get("ms"), "ok" if e.get("ok") else "FAIL", e.get("error") or ""))
'
else
  echo "(no audit file yet)"
fi
