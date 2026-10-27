#!/usr/bin/env python3
"""MCP server for the headless M5StickC (MicroPython + onboard shell).

Transport: stdio. Port comes from ESP32_PORT (default /dev/ttyUSB0).
"""
import os
import subprocess
import time

import serial
from mcp.server.mcpserver import MCPServer

import esp_common as ec

PORT = ec.PORT
MPRE = ["uvx", "mpremote", "connect", PORT]

mcp = MCPServer("esp32")


def _run_local(cmd, timeout=180):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


@mcp.tool()
def shell(command: str) -> str:
    """Run one command in the device shell and return the output.

    Available: help, chip, df, bat, temp, imu [n], wifi, rssi <ssid>, i2c,
    pins, led on|off|blink, buzz [hz] [ms], melody, bench, cpu [mhz],
    uptime, py <code>, reboot.
    """
    return ec.run(command)


@mcp.tool()
def py(code: str) -> str:
    """Evaluate a Python one-liner on the device. `stick`, `machine` and `time` are in scope."""
    return ec.py(code)


@mcp.tool()
def exec_code(code: str) -> str:
    """Run arbitrary multi-line Python on the device through mpremote.

    Interrupts the onboard shell; it is restarted afterwards.
    """
    ec.pause(90)
    try:
        with ec.port_lock():
            out = _run_local(MPRE + ["exec", code])
            _run_local(MPRE + ["reset"], timeout=40)
    finally:
        ec.resume()
    return out


@mcp.tool()
def info() -> str:
    """Chip, memory, filesystem, battery and sensor summary."""
    return ec.run("chip") + "\n" + ec.run("bat") + "\n" + ec.run("i2c")


@mcp.tool()
def reset() -> str:
    """Hard-reset the board and return the boot log."""
    return ec.reset()


@mcp.tool()
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


@mcp.tool()
def ls() -> str:
    """List files on the device filesystem."""
    ec.pause(60)
    try:
        with ec.port_lock():
            return _run_local(MPRE + ["ls"], timeout=60)
    finally:
        ec.resume()


@mcp.tool()
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


if __name__ == "__main__":
    mcp.run()
