#!/usr/bin/env python3
"""Turn buttons A/B into a two-key macro pad.

Button A (GPIO37) and B (GPIO39) read 0 when pressed. On each press the
configured command runs on the host.

    BTN_A_CMD='hyprlock' BTN_B_CMD='notify-send M5 "button B"' \
        ./scripts/macro_pad.py
"""
import json
import os
import subprocess
import time
import urllib.request

DASH = os.environ.get("ESP32_DASH", "http://127.0.0.1:8770")
POLL = float(os.environ.get("POLL_SECONDS", "0.3"))
CMDS = {
    "A": os.environ.get("BTN_A_CMD", "notify-send M5 'button A'"),
    "B": os.environ.get("BTN_B_CMD", "notify-send M5 'button B'"),
}


def state():
    with urllib.request.urlopen(DASH + "/api/state", timeout=3) as r:
        return json.loads(r.read())


def main():
    print("macro pad: A=%r B=%r" % (CMDS["A"], CMDS["B"]), flush=True)
    prev = None
    while True:
        try:
            s = state()
            btn = tuple(s.get("btn", [1, 1]))
            if prev is not None and btn != prev:
                for name, old, new in (("A", prev[0], btn[0]), ("B", prev[1], btn[1])):
                    if old != new and new == 0:
                        print(time.strftime("%H:%M:%S"), "press", name, "->", CMDS[name], flush=True)
                        subprocess.Popen(CMDS[name], shell=True)
            prev = btn
        except Exception as e:
            print(time.strftime("%H:%M:%S"), "error:", e, flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
