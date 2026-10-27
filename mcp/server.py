#!/usr/bin/env python3
"""MCP server for the headless M5StickC (MicroPython + onboard shell).

Transport: stdio. Port comes from ESP32_PORT (default /dev/ttyUSB0).
Every tool call is appended to ~/.local/state/esp32-mcp/audit.jsonl.
"""
import functools
import inspect
import json
import os
import subprocess
import threading
import time

import serial  # noqa: F401  (kept for the direct-serial path in esp_common)
from mcp.server.mcpserver import MCPServer

import esp_common as ec

PORT = ec.PORT
MPRE = ["uvx", "mpremote", "connect", PORT]

STATE_DIR = os.environ.get("ESP32_MCP_STATE", os.path.expanduser("~/.local/state/esp32-mcp"))
AUDIT = os.path.join(STATE_DIR, "audit.jsonl")
REC_DIR = os.path.join(STATE_DIR, "recordings")
os.makedirs(REC_DIR, exist_ok=True)

mcp = MCPServer("esp32")
_ALOCK = threading.Lock()


# ---------------------------------------------------------------- audit log
def _audit(entry):
    try:
        with _ALOCK:
            if os.path.exists(AUDIT) and os.path.getsize(AUDIT) > 2_000_000:
                os.replace(AUDIT, AUDIT + ".1")
            with open(AUDIT, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _audit_tail(n=20):
    try:
        with open(AUDIT) as f:
            lines = f.readlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.time()
        result = None
        error = None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            error = str(e)
            raise
        finally:
            try:
                params = dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
                for key in list(params):
                    if any(word in key.lower() for word in ("pass", "secret", "token")):
                        params[key] = "***"
                preview = result if isinstance(result, str) else repr(result)
                _audit(
                    {
                        "ts": time.time(),
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "tool": fn.__name__,
                        "args": params,
                        "ms": int((time.time() - t0) * 1000),
                        "ok": error is None,
                        "error": error,
                        "result": (preview or "")[:500],
                    }
                )
            except Exception:
                pass

    return wrapper


def _run_local(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def _py_repr(value):
    """repr() that MicroPython understands (bytes -> str via utf-8)."""
    return repr(value)


# ---------------------------------------------------------------- core
@mcp.tool()
@logged
def shell(command: str) -> str:
    """Run one command in the device shell.

    Commands: help, chip, df, bat, temp, imu [n], wifi [scan|status|connect|off],
    rssi <ssid>, i2c [scan|r|w], pins, pin, adc, pwm, led, buzz, melody,
    cpu, uptime, bench, log, deepsleep, py, sample, reboot.
    """
    return ec.run(command)


@mcp.tool()
@logged
def py(code: str) -> str:
    """Evaluate a Python one-liner on the device (`stick`, `machine`, `time` in scope)."""
    return ec.py(code)


@mcp.tool()
@logged
def exec_code(code: str) -> str:
    """Run multi-line Python on the device through mpremote (shell restarts after)."""
    ec.pause(90)
    try:
        with ec.port_lock():
            out = _run_local(MPRE + ["exec", code])
            _run_local(MPRE + ["reset"], timeout=40)
    finally:
        ec.resume()
    return out


@mcp.tool()
@logged
def status() -> str:
    """Host + device summary: dashboard, port, uptime, battery, motion."""
    lines = ["port: %s" % PORT]
    if ec.dash_alive():
        try:
            st = ec._dash("/api/state", timeout=2)
            lines.append("dashboard: up (%s)" % ec.DASH)
            lines.append("online: %s  uptime: %ss" % (st.get("online"), st.get("uptime")))
            lines.append("battery: %.2f V (%s%%)  charge %.1f mA  load %.1f mA"
                         % (st.get("volts", 0), st.get("pct", 0), st.get("charge", 0), st.get("load", 0)))
            lines.append("motion: %s  score %.3f g/s" % (st.get("motion"), st.get("score", 0)))
            lines.append("buttons: A=%s B=%s" % tuple(st.get("btn", [1, 1])))
            if st.get("last_recording"):
                rec = st["last_recording"]
                lines.append("last recording: %s (%s rows)" % (rec.get("name"), rec.get("rows")))
        except Exception as e:
            lines.append("dashboard: error %s" % e)
    else:
        lines.append("dashboard: down (direct serial mode)")
    return "\n".join(lines)


@mcp.tool()
@logged
def info() -> str:
    """Chip, memory, filesystem, battery and I2C summary."""
    return ec.run("chip") + "\n" + ec.run("bat") + "\n" + ec.run("i2c")


@mcp.tool()
@logged
def battery() -> str:
    """Battery voltage, percentage, charge/discharge current and AXP status."""
    return ec.run("bat")


@mcp.tool()
@logged
def sensors(n: int = 1, delay_ms: int = 200) -> str:
    """Read the IMU n times (accel g + gyro dps)."""
    n = max(1, min(200, int(n)))
    if n == 1:
        return ec.run("imu 1")
    return ec.run("imu %d" % n, timeout=10 + n * delay_ms / 1000.0)


@mcp.tool()
@logged
def buttons() -> str:
    """Current state of buttons A and B (0 = pressed)."""
    return ec.run("pins")


# ---------------------------------------------------------------- actuators
@mcp.tool()
@logged
def led(state: str = "on") -> str:
    """Control the red LED: on, off or blink."""
    state = state.lower()
    if state not in ("on", "off", "blink"):
        raise ValueError("state must be on|off|blink")
    return ec.run("led " + state)


@mcp.tool()
@logged
def buzz(freq: int = 2000, ms: int = 120) -> str:
    """Beep the buzzer at freq Hz for ms milliseconds."""
    return ec.run("buzz %d %d" % (int(freq), int(ms)))


@mcp.tool()
@logged
def melody() -> str:
    """Play a short melody on the buzzer."""
    return ec.run("melody")


@mcp.tool()
@logged
def gpio(pin: int, mode: str = "in", value: int = 0) -> str:
    """Read (mode=in) or write (mode=out) a GPIO pin."""
    if mode.lower() == "in":
        return ec.run("pin %d in" % int(pin))
    return ec.run("pin %d %d" % (int(pin), 1 if value else 0))


@mcp.tool()
@logged
def adc(pin: int) -> str:
    """Read an ADC pin: raw value and approximate millivolts."""
    return ec.run("adc %d" % int(pin))


@mcp.tool()
@logged
def pwm(pin: int, freq: int = 0, duty: int = 512) -> str:
    """Start PWM on a pin (freq>0) or stop it (freq=0)."""
    if int(freq) <= 0:
        return ec.run("pwm %d off" % int(pin))
    return ec.run("pwm %d %d %d" % (int(pin), int(freq), int(duty)))


# ---------------------------------------------------------------- i2c
@mcp.tool()
@logged
def i2c_scan() -> str:
    """Scan the I2C bus and list device addresses."""
    return ec.run("i2c")


@mcp.tool()
@logged
def i2c_read(addr: int, reg: int, n: int = 1) -> str:
    """Read n bytes from an I2C register (addr/reg may be decimal)."""
    return ec.run("i2c r %d %d %d" % (int(addr), int(reg), int(n)))


@mcp.tool()
@logged
def i2c_write(addr: int, reg: int, value: int) -> str:
    """Write one byte to an I2C register."""
    return ec.run("i2c w %d %d %d" % (int(addr), int(reg), int(value)))


# ---------------------------------------------------------------- wifi
@mcp.tool()
@logged
def wifi_scan() -> str:
    """Scan 2.4 GHz networks (2-4 s)."""
    return ec.run("wifi", timeout=30)


@mcp.tool()
@logged
def wifi_rssi(ssid: str) -> str:
    """RSSI of one SSID (spaces supported)."""
    return ec.py("print(stick.rssi(%s))" % _py_repr(ssid))


@mcp.tool()
@logged
def wifi_status() -> str:
    """Wi-Fi connection state, SSID, RSSI and IP."""
    return ec.run("wifi status")


@mcp.tool()
@logged
def wifi_connect(ssid: str, password: str) -> str:
    """Connect to a Wi-Fi network (password is redacted in the audit log)."""
    return ec.py("print(stick.wifi_connect(%s, %s))" % (_py_repr(ssid), _py_repr(password)), timeout=30)


@mcp.tool()
@logged
def wifi_disconnect() -> str:
    """Disconnect and turn the Wi-Fi radio off."""
    return ec.run("wifi off")


# ---------------------------------------------------------------- filesystem
@mcp.tool()
@logged
def files() -> str:
    """List files on the device filesystem."""
    return ec.py("import os;print(os.listdir())")


@mcp.tool()
@logged
def read_file(path: str, max_bytes: int = 4096) -> str:
    """Read a text file from the device (up to max_bytes)."""
    return ec.py("print(open(%s).read(%d))" % (_py_repr(path), int(max_bytes)))


@mcp.tool()
@logged
def write_file(path: str, content: str) -> str:
    """Write text to a device file (base64 transfer, safe for any content)."""
    import base64

    blob = base64.b64encode(content.encode()).decode()
    ec.py(
        "import ubinascii;open(%s,'wb').write(ubinascii.a2b_base64(%s))"
        % (_py_repr(path), _py_repr(blob))
    )
    return ec.py("import os;print(os.stat(%s)[6])" % _py_repr(path))


@mcp.tool()
@logged
def remove_file(path: str) -> str:
    """Delete a file from the device."""
    ec.py("import os;os.remove(%s)" % _py_repr(path))
    return "removed: " + path


# ---------------------------------------------------------------- logs
@mcp.tool()
@logged
def device_log(lines: int = 50) -> str:
    """Read the on-device command log (8 KiB ring with one rotation)."""
    return ec.run("log %d" % max(1, min(200, int(lines))))


@mcp.tool()
@logged
def clear_device_log() -> str:
    """Erase the on-device log."""
    return ec.run("log clear")


@mcp.tool()
@logged
def events(n: int = 20) -> str:
    """Recent dashboard events (motion, buttons, commands, errors)."""
    if not ec.dash_alive():
        return "dashboard is down; start it with: systemctl --user start esp32-dashboard"
    data = ec._dash("/api/logs?n=%d" % max(1, min(200, int(n))), timeout=5)
    out = []
    for e in data.get("entries", []):
        out.append("%s  %-6s  %s" % (e.get("iso"), e.get("kind"), e.get("text")))
    return "\n".join(out) or "(no events)"


@mcp.tool()
@logged
def audit_log(n: int = 20) -> str:
    """Tail of the MCP audit log (tool, args, ms, ok)."""
    out = []
    for e in _audit_tail(max(1, min(200, int(n)))):
        out.append(
            "%s  %-12s %5sms  %s  %s"
            % (e.get("iso"), e.get("tool"), e.get("ms"), "ok" if e.get("ok") else "FAIL", e.get("error") or "")
        )
    return "\n".join(out) or "(no audit entries)"


# ---------------------------------------------------------------- recording
@mcp.tool()
@logged
def record(seconds: int = 10) -> str:
    """Record IMU to CSV for N seconds; returns file path and min/max/mean."""
    seconds = max(1, min(120, int(seconds)))
    if ec.dash_alive():
        res = ec._dash("/api/record", {"seconds": seconds}, timeout=seconds + 25)
        if res.get("ok"):
            return "saved %s\nrows=%s mean=%s g spread=%s g\n%s" % (
                res.get("name"),
                res.get("rows"),
                res.get("mean_g"),
                res.get("spread_g"),
                res.get("path"),
            )
        raise RuntimeError(res.get("error", "recording failed"))

    # fallback: sample directly over serial
    import math

    name = time.strftime("imu-%Y%m%d-%H%M%S.csv")
    path = os.path.join(REC_DIR, name)
    rows, mags = 0, []
    t0 = time.time()
    with open(path, "w") as f:
        f.write("t,ax,ay,az,gx,gy,gz\n")
        while time.time() - t0 < seconds:
            parts = ec.run("sample").strip().split(",")
            if len(parts) >= 6:
                v = [float(x) for x in parts[:6]]
                f.write("%.2f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f\n" % ((time.time() - t0,) + tuple(v)))
                mags.append(math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2))
                rows += 1
            time.sleep(0.2)
    if not mags:
        raise RuntimeError("no samples recorded")
    return "saved %s\nrows=%d mean=%.3f g spread=%.3f g\n%s" % (
        name,
        rows,
        sum(mags) / len(mags),
        max(mags) - min(mags),
        path,
    )


# ---------------------------------------------------------------- power / reset
@mcp.tool()
@logged
def reboot() -> str:
    """Reboot the board."""
    try:
        return ec.run("reboot", timeout=5)
    except Exception:
        return "reboot sent"


@mcp.tool()
@logged
def reset() -> str:
    """Hard-reset the board and return the boot log."""
    return ec.reset()


@mcp.tool()
@logged
def bootlog(seconds: float = 5.0) -> str:
    """Reset the board and capture the raw serial boot log."""
    ec.pause(seconds + 10)
    try:
        with ec.port_lock():
            with ec._open() as ser:
                ser.setDTR(False)
                ser.setRTS(True)
                time.sleep(0.12)
                ser.setRTS(False)
                time.sleep(max(0.5, seconds))
                return ec.read_until(ser, marker=b"__never__", timeout=0.3).decode("utf-8", "replace")
    finally:
        ec.resume()


# ---------------------------------------------------------------- transfer
@mcp.tool()
@logged
def upload(local_path: str, remote_path: str) -> str:
    """Copy a local file to the device and restart the shell."""
    ec.pause(150)
    try:
        with ec.port_lock():
            out = _run_local(MPRE + ["cp", local_path, ":" + remote_path], timeout=120)
            _run_local(MPRE + ["reset"], timeout=40)
    finally:
        ec.resume()
    return out or "ok"


@mcp.tool()
@logged
def download(remote_path: str, local_path: str) -> str:
    """Copy a file from the device to the local machine."""
    ec.pause(60)
    try:
        with ec.port_lock():
            out = _run_local(MPRE + ["cp", ":" + remote_path, local_path], timeout=120)
    finally:
        ec.resume()
    return out or "ok"


@mcp.tool()
@logged
def port_status() -> str:
    """Serial port and dashboard reachability."""
    lines = ["port: %s @ %s" % (PORT, ec.BAUD), "dashboard: %s" % ("up" if ec.dash_alive() else "down")]
    try:
        with ec.port_lock(2):
            with ec._open():
                lines.append("uart: openable")
    except Exception as e:
        lines.append("uart: busy (%s)" % e)
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
