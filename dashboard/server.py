#!/usr/bin/env python3
"""Local web dashboard for the headless M5StickC.

Run:  uv run --with pyserial python dashboard/server.py
Open: http://127.0.0.1:8770

The dashboard owns the UART for its whole lifetime (a single worker thread),
which avoids byte loss from open/close churn. Other processes (opencode MCP)
go through POST /api/cmd instead of opening the port themselves.
"""
import json
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(HERE, "..", "mcp"), os.path.expanduser("~/.config/opencode/mcp/esp32")):
    _cand = os.path.abspath(_cand)
    if os.path.isfile(os.path.join(_cand, "esp_common.py")):
        sys.path.insert(0, _cand)
        break

import esp_common as ec  # noqa: E402

PORT = int(os.environ.get("DASH_PORT", "8770"))

SAMPLE = "sample"

STATE = {
    "online": False,
    "ts": 0,
    "imu": [0.0] * 6,
    "volts": 0.0,
    "pct": 0,
    "charge": 0.0,
    "load": 0.0,
    "btn": [1, 1],
    "uptime": 0,
    "motion": False,
    "score": 0.0,
    "wifi": [],
    "events": [],
}
SLOCK = threading.Lock()
CFG = {"threshold": 0.06}


def log_event(text):
    with SLOCK:
        STATE["events"].insert(0, {"t": time.strftime("%H:%M:%S"), "text": text})
        del STATE["events"][60:]


class Worker(threading.Thread):
    """Single owner of the serial port."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.ser = None
        self.paused_until = 0.0
        self.last_acc = None
        self.score = 0.0
        self.fail = 0

    # -- plumbing ---------------------------------------------------------
    def _open(self):
        self.ser = ec._open()
        ec.sync(self.ser)

    def _close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def pause(self, seconds=20.0):
        self.paused_until = time.time() + seconds
        self._close()
        time.sleep(0.4)  # let an in-flight write settle

    def resume(self):
        self.paused_until = 0.0

    def _write_read(self, command, timeout):
        if self.paused_until > time.time():
            raise RuntimeError("port paused for flashing")
        if self.ser is None:
            self._open()
        self.ser.reset_input_buffer()
        self.ser.write((command + "\r\n").encode())
        raw = ec.read_until(self.ser, timeout=timeout)
        return ec.clean(raw, command)

    def exec(self, command, timeout=10.0):
        """Run a command synchronously from a request thread."""
        if self.paused_until > time.time():
            raise RuntimeError("port paused for flashing")
        fut = {"ev": threading.Event(), "out": None, "err": None}
        self.q.put((command, timeout, fut))
        if not fut["ev"].wait(timeout + 8):
            raise TimeoutError("device did not answer")
        if fut["err"]:
            raise fut["err"]
        return fut["out"]

    # -- main loop --------------------------------------------------------
    def run(self):
        while True:
            if self.paused_until > time.time():
                time.sleep(0.1)
                continue
            try:
                command, timeout, fut = self.q.get_nowait()
            except queue.Empty:
                self._sample()
                continue
            try:
                fut["out"] = self._write_read(command, timeout)
            except Exception as e:
                fut["err"] = e
                self._close()
            fut["ev"].set()

    def _sample(self):
        try:
            raw = self._write_read(SAMPLE, timeout=6)
            parts = [p for p in raw.strip().split(",") if p]
            if len(parts) < 13:
                self.fail += 1
                if self.fail in (1, 10, 100):
                    log_event("bad sample (%d): %r" % (self.fail, raw[:60]))
                time.sleep(0.3)
                return
            self.fail = 0
            vals = [float(p) for p in parts[:13]]
        except Exception as e:
            self._close()
            if self.paused_until > time.time():
                time.sleep(0.2)
                return
            with SLOCK:
                STATE["online"] = False
            log_event("serial error: %s" % e)
            time.sleep(0.5)
            return

        imu = vals[0:6]
        acc = imu[0:3]
        if self.last_acc is not None:
            jerk = sum((a - b) ** 2 for a, b in zip(acc, self.last_acc)) ** 0.5
            self.score = self.score * 0.75 + jerk * 0.25
        self.last_acc = acc
        moving = self.score > CFG["threshold"]

        with SLOCK:
            was = STATE["motion"]
            STATE.update(
                online=True,
                ts=time.time(),
                imu=imu,
                volts=vals[6],
                pct=int(vals[7]),
                charge=vals[8],
                load=vals[9],
                btn=[int(vals[10]), int(vals[11])],
                uptime=int(vals[12]),
                motion=moving,
                score=round(self.score, 4),
            )
        if moving and not was:
            log_event("motion detected (%.2f g/s)" % self.score)


WORKER = Worker()


def wifi_scan():
    try:
        out = WORKER.exec("wifi", timeout=30)
        nets = []
        for line in out.splitlines():
            m = re.match(r"^(.*?)\s+(-?\d+)\s+(\d+)\s+(\d+)\s*$", line)
            if m and m.group(1).strip() != "ssid":
                nets.append(
                    {"ssid": m.group(1).strip() or "<hidden>", "rssi": int(m.group(2)), "ch": int(m.group(3))}
                )
        with SLOCK:
            STATE["wifi"] = nets[:30]
        log_event("wifi scan: %d networks" % len(nets))
        return nets
    except Exception as e:
        log_event("wifi scan failed: %s" % e)
        return []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            with SLOCK:
                self._json(200, STATE)
        elif self.path == "/api/ping":
            self._json(200, {"ok": True, "port": ec.PORT})
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    with SLOCK:
                        payload = json.dumps(STATE)
                    self.wfile.write(("data: " + payload + "\n\n").encode())
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}

        if self.path == "/api/cmd":
            cmd = (body.get("command") or "").strip()
            if not cmd:
                return self._json(400, {"error": "empty command"})
            try:
                out = WORKER.exec(cmd, timeout=30)
                self._json(200, {"ok": True, "output": out})
            except Exception as e:
                self._json(200, {"ok": False, "output": str(e)})
        elif self.path == "/api/wifi":
            threading.Thread(target=wifi_scan, daemon=True).start()
            self._json(200, {"ok": True})
        elif self.path == "/api/motion":
            CFG["threshold"] = float(body.get("threshold", CFG["threshold"]))
            self._json(200, {"ok": True, "threshold": CFG["threshold"]})
        elif self.path == "/api/pause":
            WORKER.pause(float(body.get("seconds", 20)))
            self._json(200, {"ok": True})
        elif self.path == "/api/resume":
            WORKER.resume()
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})


def main():
    WORKER.start()
    threading.Timer(2.0, wifi_scan).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("dashboard: http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
