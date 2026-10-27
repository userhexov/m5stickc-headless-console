#!/usr/bin/env python3
"""Log RSSI of one SSID to CSV via the dashboard.

    ./scripts/rssi_log.py Home_2G 10 ~/rssi.csv

Each sample is a Wi-Fi scan (2-4 s), so keep the interval >= 5 s.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.request

DASH = os.environ.get("ESP32_DASH", "http://127.0.0.1:8770")


def cmd(command):
    req = urllib.request.Request(
        DASH + "/api/cmd",
        data=json.dumps({"command": command}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read()).get("output", "")


def main():
    if len(sys.argv) < 2:
        print("usage: rssi_log.py <ssid> [interval] [out.csv]", file=sys.stderr)
        return 1
    ssid = sys.argv[1]
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 10
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser("~/esp32-rssi.csv")
    new = not os.path.exists(out)
    with open(out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["iso", "ssid", "rssi"])
        print("logging %r every %ss -> %s" % (ssid, interval, out), flush=True)
        while True:
            try:
                text = cmd("rssi " + ssid)
                m = re.search(r"(-?\d+)\s*dBm", text)
                if m:
                    w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S"), ssid, int(m.group(1))])
                    f.flush()
                    print(time.strftime("%H:%M:%S"), m.group(1), "dBm", flush=True)
                else:
                    print(time.strftime("%H:%M:%S"), "not found:", text.strip()[:60], flush=True)
            except Exception as e:
                print(time.strftime("%H:%M:%S"), "error:", e, flush=True)
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
