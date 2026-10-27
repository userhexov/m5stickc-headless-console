#!/usr/bin/env python3
"""Local web dashboard for the headless M5StickC.

Run:  uv run --with pyserial python dashboard/server.py
Open: http://127.0.0.1:8770

The dashboard owns the UART for its whole lifetime (a single worker thread),
which avoids byte loss from open/close churn. Other processes (opencode MCP)
go through POST /api/cmd instead of opening the port themselves.

Logs:
  $XDG_STATE_HOME/esp32-dashboard/events.jsonl   structured host events
  $XDG_STATE_HOME/esp32-dashboard/recordings/    IMU CSV recordings
"""
import json
import math
import os
import queue
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(HERE, "..", "mcp"), os.path.expanduser("~/.config/opencode/mcp/esp32")):
    _cand = os.path.abspath(_cand)
    if os.path.isfile(os.path.join(_cand, "esp_common.py")):
        sys.path.insert(0, _cand)
        break

import esp_common as ec  # noqa: E402

PORT = int(os.environ.get("DASH_PORT", "8770"))
STATE_DIR = os.environ.get(
    "ESP32_STATE_DIR", os.path.expanduser("~/.local/state/esp32-dashboard")
)
EVENTS_LOG = os.path.join(STATE_DIR, "events.jsonl")
REC_DIR = os.path.join(STATE_DIR, "recordings")
WEBHOOK = os.environ.get("ESP32_WEBHOOK", "")
os.makedirs(REC_DIR, exist_ok=True)

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
    "recording": False,
    "last_recording": None,
    "host_uptime": 0,
}
SLOCK = threading.Lock()
FLOCK = threading.Lock()
CFG = {"threshold": 0.06}
STARTED = time.time()


def _append_jsonl(path, entry):
    try:
        with FLOCK:
            if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
                os.replace(path, path + ".1")
            with open(path, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_jsonl_tail(path, n=100):
    try:
        with open(path) as f:
            lines = f.readlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def log_event(text, kind="info", **extra):
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "kind": kind,
        "text": text,
    }
    entry.update(extra)
    with SLOCK:
        STATE["events"].insert(0, {"t": time.strftime("%H:%M:%S"), "text": text, "kind": kind})
        del STATE["events"][80:]
    _append_jsonl(EVENTS_LOG, entry)
    if WEBHOOK and kind in ("motion", "button"):
        _notify(dict(entry, event=kind))


def _notify(payload):
    def go():
        try:
            req = urllib.request.Request(
                WEBHOOK,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=3).read()
        except Exception as e:
            _append_jsonl(
                EVENTS_LOG,
                {
                    "ts": time.time(),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "kind": "error",
                    "text": "webhook failed: %s" % e,
                },
            )

    threading.Thread(target=go, daemon=True).start()


class Worker(threading.Thread):
    """Single owner of the serial port."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.ser = None
        self.paused_until = 0.0
        self.last_acc = None
        self.last_btn = None
        self.score = 0.0
        self.fail = 0

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
        time.sleep(0.4)

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
        if self.paused_until > time.time():
            raise RuntimeError("port paused for flashing")
        fut = {"ev": threading.Event(), "out": None, "err": None}
        self.q.put((command, timeout, fut))
        if not fut["ev"].wait(timeout + 8):
            raise TimeoutError("device did not answer")
        if fut["err"]:
            raise fut["err"]
        return fut["out"]

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
        raw = ""
        vals = None
        serial_error = None
        # The FTDI bridge occasionally drops the first bytes of a short line
        # ("sample" -> "smple"). One immediate retry hides that without
        # touching the 5 Hz cadence.
        for _attempt in (1, 2):
            try:
                raw = self._write_read(SAMPLE, timeout=6)
            except Exception as e:
                serial_error = e
                self._close()
                break
            parts = [p for p in raw.strip().split(",") if p]
            if len(parts) >= 13:
                try:
                    vals = [float(p) for p in parts[:13]]
                    break
                except ValueError:
                    pass

        if vals is None:
            if serial_error is not None:
                if self.paused_until > time.time():
                    time.sleep(0.2)
                    return
                with SLOCK:
                    STATE["online"] = False
                log_event("serial error: %s" % serial_error, kind="error")
                time.sleep(0.5)
                return
            self.fail += 1
            if self.fail in (1, 10, 100):
                log_event("bad sample (%d): %r" % (self.fail, raw[:60]), kind="error")
            time.sleep(0.2)
            return
        self.fail = 0

        imu = vals[0:6]
        acc = imu[0:3]
        if self.last_acc is not None:
            jerk = sum((a - b) ** 2 for a, b in zip(acc, self.last_acc)) ** 0.5
            self.score = self.score * 0.75 + jerk * 0.25
        self.last_acc = acc
        moving = self.score > CFG["threshold"]
        btn = [int(vals[10]), int(vals[11])]

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
                btn=btn,
                uptime=int(vals[12]),
                motion=moving,
                score=round(self.score, 4),
                host_uptime=int(time.time() - STARTED),
            )

        if moving and not was:
            log_event("motion detected (%.2f g/s)" % self.score, kind="motion", score=round(self.score, 4))
        if self.last_btn is not None and btn != self.last_btn:
            for name, old, new in (("A", self.last_btn[0], btn[0]), ("B", self.last_btn[1], btn[1])):
                if old != new:
                    log_event("button %s %s" % (name, "pressed" if new == 0 else "released"), kind="button", button=name)
        self.last_btn = btn


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
        log_event("wifi scan: %d networks" % len(nets), kind="wifi")
        return nets
    except Exception as e:
        log_event("wifi scan failed: %s" % e, kind="error")
        return []


def record(seconds=10):
    seconds = max(1, min(120, int(seconds)))
    name = time.strftime("imu-%Y%m%d-%H%M%S.csv")
    path = os.path.join(REC_DIR, name)
    rows = 0
    mags = []
    with SLOCK:
        STATE["recording"] = True
    t0 = time.time()
    try:
        with open(path, "w") as f:
            f.write("t,ax,ay,az,gx,gy,gz,volts,pct,btnA,btnB\n")
            while time.time() - t0 < seconds:
                with SLOCK:
                    s = dict(STATE)
                    imu = list(s["imu"])
                if s["online"]:
                    t = time.time() - t0
                    f.write(
                        "%.2f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.2f,%d,%d,%d\n"
                        % (t, imu[0], imu[1], imu[2], imu[3], imu[4], imu[5], s["volts"], s["pct"], s["btn"][0], s["btn"][1])
                    )
                    mags.append(math.sqrt(imu[0] ** 2 + imu[1] ** 2 + imu[2] ** 2))
                    rows += 1
                time.sleep(0.2)
    finally:
        with SLOCK:
            STATE["recording"] = False

    summary = {"rows": rows, "seconds": round(time.time() - t0, 1)}
    if mags:
        summary.update(
            mean_g=round(sum(mags) / len(mags), 3),
            min_g=round(min(mags), 3),
            max_g=round(max(mags), 3),
            spread_g=round(max(mags) - min(mags), 3),
        )
    result = {"path": path, "name": name, **summary}
    with SLOCK:
        STATE["last_recording"] = result
    log_event("recording %s: %d rows, spread %s g" % (name, rows, summary.get("spread_g")), kind="record", path=path, rows=rows)
    return result


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
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            with SLOCK:
                self._json(200, STATE)
        elif path == "/api/ping":
            self._json(200, {"ok": True, "port": ec.PORT, "state_dir": STATE_DIR, "webhook": bool(WEBHOOK)})
        elif path == "/api/logs":
            n = 100
            if "n=" in self.path:
                try:
                    n = int(self.path.split("n=")[1].split("&")[0])
                except Exception:
                    pass
            self._json(200, {"entries": _read_jsonl_tail(EVENTS_LOG, max(1, min(1000, n)))})
        elif path == "/api/device-log":
            n = 50
            if "n=" in self.path:
                try:
                    n = int(self.path.split("n=")[1].split("&")[0])
                except Exception:
                    pass
            try:
                self._json(200, {"ok": True, "output": WORKER.exec("log %d" % max(1, min(200, n)), timeout=15)})
            except Exception as e:
                self._json(200, {"ok": False, "output": str(e)})
        elif path == "/api/recordings":
            items = []
            for name in sorted(os.listdir(REC_DIR), reverse=True):
                if not name.endswith(".csv"):
                    continue
                full = os.path.join(REC_DIR, name)
                items.append({"name": name, "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
            self._json(200, {"dir": REC_DIR, "items": items[:50]})
        elif path == "/events":
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
            t0 = time.time()
            try:
                out = WORKER.exec(cmd, timeout=30)
                ms = int((time.time() - t0) * 1000)
                if cmd != "sample":
                    log_event("cmd: %s" % cmd, kind="cmd", ms=ms, ok=True)
                self._json(200, {"ok": True, "output": out, "ms": ms})
            except Exception as e:
                log_event("cmd failed: %s (%s)" % (cmd, e), kind="error")
                self._json(200, {"ok": False, "output": str(e)})
        elif self.path == "/api/wifi":
            threading.Thread(target=wifi_scan, daemon=True).start()
            self._json(200, {"ok": True})
        elif self.path == "/api/motion":
            CFG["threshold"] = float(body.get("threshold", CFG["threshold"]))
            log_event("motion threshold -> %.2f" % CFG["threshold"], kind="config")
            self._json(200, {"ok": True, "threshold": CFG["threshold"]})
        elif self.path == "/api/record":
            try:
                self._json(200, {"ok": True, **record(body.get("seconds", 10))})
            except Exception as e:
                self._json(200, {"ok": False, "error": str(e)})
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
    log_event("dashboard started on port %d" % PORT, kind="system", state_dir=STATE_DIR)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("dashboard: http://127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
