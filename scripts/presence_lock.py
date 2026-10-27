#!/usr/bin/env python3
"""Lock the screen when the stick has not moved for N seconds.

The stick sits on the desk; walking away stops the IMU vibrations, so after
IDLE_SECONDS the configured lock command runs. Any motion resets the timer.

    IDLE_SECONDS=300 LOCK_CMD=hyprlock ./scripts/presence_lock.py
"""
import json
import os
import subprocess
import time
import urllib.request

DASH = os.environ.get("ESP32_DASH", "http://127.0.0.1:8770")
IDLE = int(os.environ.get("IDLE_SECONDS", "300"))
POLL = float(os.environ.get("POLL_SECONDS", "2"))
LOCK = os.environ.get("LOCK_CMD", "hyprlock").split()


def state():
    with urllib.request.urlopen(DASH + "/api/state", timeout=3) as r:
        return json.loads(r.read())


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    say("presence: idle=%ss poll=%ss lock=%s" % (IDLE, POLL, " ".join(LOCK)))
    last = time.time()
    locked = False
    while True:
        try:
            s = state()
            if s.get("motion"):
                last = time.time()
                if locked:
                    say("motion: user is back")
                    locked = False
            idle = time.time() - last
            if idle >= IDLE and not locked:
                say("idle %.0fs -> %s" % (idle, " ".join(LOCK)))
                subprocess.Popen(LOCK)
                locked = True
        except Exception as e:
            say("error: %s" % e)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
