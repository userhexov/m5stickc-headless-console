"""Shared serial access for the M5StickC (used by MCP server and web dashboard).

A cross-process file lock keeps the single UART from being grabbed by two
processes at once (opencode MCP and the dashboard).
"""
import fcntl
import json
import os
import tempfile
import time
import urllib.request

import serial

PORT = os.environ.get("ESP32_PORT", "/dev/ttyUSB0")
BAUD = int(os.environ.get("ESP32_BAUD", "115200"))
PROMPT = b"esp32> "
LOCK_PATH = os.environ.get("ESP32_LOCK", os.path.join(tempfile.gettempdir(), "esp32-port.lock"))
DASH = os.environ.get("ESP32_DASH", "http://127.0.0.1:8770")


def _dash(path, payload=None, timeout=3.0):
    url = DASH + path
    if payload is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def dash_alive():
    try:
        _dash("/api/ping", timeout=0.6)
        return True
    except Exception:
        return False


def pause(seconds=30.0):
    """Ask the dashboard to release the UART (for mpremote/esptool)."""
    try:
        _dash("/api/pause", {"seconds": seconds}, timeout=2.0)
    except Exception:
        pass


def resume():
    try:
        _dash("/api/resume", {}, timeout=2.0)
    except Exception:
        pass


class PortBusy(TimeoutError):
    pass


class _Lock:
    def __init__(self, timeout=20.0):
        self.timeout = timeout
        self.fh = None

    def __enter__(self):
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        self.fh = open(LOCK_PATH, "w")
        end = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > end:
                    self.fh.close()
                    raise PortBusy("serial port is busy")
                time.sleep(0.03)

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def port_lock(timeout=20.0):
    return _Lock(timeout)


def _open():
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    ser.setDTR(False)
    ser.setRTS(False)
    return ser


def read_until(ser, marker=PROMPT, timeout=20.0):
    end = time.time() + timeout
    buf = b""
    while time.time() < end:
        chunk = ser.read(4096)
        if chunk:
            buf += chunk
            if marker in buf:
                break
        else:
            time.sleep(0.005)
    return buf


def sync(ser, wait=8.0):
    """Ensure the onboard shell prompt is available.

    Sequence is deliberately gentle: newline -> Ctrl-C -> Ctrl-D, checking for
    the prompt after each step. Ctrl-D is only sent when the shell is really
    not answering, because it soft-resets the board.
    """
    ser.reset_input_buffer()
    buf = b""
    for _ in range(3):
        ser.write(b"\r\n")
        buf += read_until(ser, timeout=1.2)
        if PROMPT in buf:
            return buf
        ser.write(b"\x03")  # Ctrl-C: leave running code / REPL
        buf += read_until(ser, timeout=0.6)
        if PROMPT in buf:
            return buf
        ser.write(b"\x04")  # Ctrl-D: soft reset -> runs main.py
        buf += read_until(ser, timeout=wait)
        if PROMPT in buf:
            return buf
    return buf


def clean(raw, command=None):
    text = raw.decode("utf-8", "replace").replace("\r", "")
    text = text.replace("esp32> ", "")
    if command:
        text = text.replace(command + "\n", "", 1)
    return text.strip("\n")


def run(command, timeout=25.0):
    """Run one shell command, returning cleaned output.

    Prefers the dashboard (single owner of the UART) when it is running.
    """
    command = command.strip()
    if dash_alive():
        try:
            j = _dash("/api/cmd", {"command": command}, timeout=timeout + 6)
            return j.get("output", "")
        except Exception:
            pass
    with port_lock():
        with _open() as ser:
            sync(ser)
            ser.write((command + "\r\n").encode())
            raw = read_until(ser, timeout=timeout)
    return clean(raw, command)


def py(code, timeout=25.0):
    return run("py " + code, timeout=timeout)


def reset(wait=0.9):
    pause(12)
    try:
        with port_lock():
            with _open() as ser:
                ser.setDTR(False)
                ser.setRTS(True)
                time.sleep(0.12)
                ser.setRTS(False)
                time.sleep(wait)
                return read_until(ser, timeout=0.4).decode("utf-8", "replace")
    finally:
        resume()
