# Headless M5StickC terminal shell
import os
import sys
import time

import stick

LOG_PATH = "log.txt"
LOG_MAX = 8192

HELP = """commands:
  help                 this text
  chip                 mcu / memory / flash info
  df                   filesystem usage
  bat                  battery: volts, %, charge/discharge mA
  temp                 chip temperature
  imu [n]              n samples of accel/gyro (default 1)
  wifi                 scan 2.4 GHz networks
  wifi status          connection state / rssi / ip
  wifi connect <ssid> <pass>
  wifi off             disconnect
  rssi <ssid>          rssi of one network (2 s scan)
  i2c                  scan bus
  i2c r <addr> <reg> [n]   read registers
  i2c w <addr> <reg> <val> write register
  pins                 button states (A, B)
  pin <gpio> in|0|1    read/write a gpio
  adc <gpio>           raw + mV
  pwm <gpio> off|freq duty
  led on|off|blink     red led
  buzz [hz] [ms]       beeper
  melody               play a short tune
  cpu [mhz]            show/set cpu frequency
  uptime               seconds since boot
  bench                cpu benchmark
  log [n]              last n log lines (default 30)
  log clear            erase the log
  deepsleep <sec>      deep sleep for n seconds
  py <code>            run a python one-liner (stick, time available)
  reboot               restart board
"""


def out(*a):
    print(*a)


def _log(text):
    """Append one line to the on-device ring log (8 KiB, one rotation)."""
    try:
        try:
            size = os.stat(LOG_PATH)[6]
        except OSError:
            size = 0
        if size > LOG_MAX:
            try:
                os.remove("log.1")
            except OSError:
                pass
            try:
                os.rename(LOG_PATH, "log.1")
            except OSError:
                pass
        with open(LOG_PATH, "a") as f:
            f.write("[%ds] %s\n" % (stick.uptime(), text))
    except Exception:
        pass


def do_chip():
    c = stick.chip()
    out("micropython :", c["mpy"])
    out("cpu         :", c["freq"] // 1000000, "MHz")
    out("uid         :", c["uid"])
    out("ram free    :", c["mem_free"], "bytes")
    out("flash       :", c["fs_free"], "/", c["fs_total"], "KiB free")


def do_bat():
    v, pct, chg, dis, st = stick.battery()
    out("voltage : %.2f V  (~%d%%)" % (v, pct))
    out("charging: %.1f mA   load: %.1f mA" % (chg, dis))
    out("status  : 0x%02x" % st)


def do_imu(args):
    n = int(args[0]) if args else 1
    stick.imu_init()
    for _ in range(n):
        ax, ay, az, gx, gy, gz = stick.imu()
        out("acc g: %6.2f %6.2f %6.2f   gyro dps: %7.1f %7.1f %7.1f" % (ax, ay, az, gx, gy, gz))
        if n > 1:
            time.sleep_ms(200)


def do_wifi(args):
    if args and args[0] == "status":
        s = stick.wifi_status()
        if not s.get("active"):
            out("wifi: off")
        elif not s.get("connected"):
            out("wifi: on, not connected")
        else:
            out("ssid:", s["ssid"])
            out("rssi:", s["rssi"], "dBm")
            out("ip  :", s["ip"])
        return
    if args and args[0] == "connect":
        if len(args) < 3:
            out("usage: wifi connect <ssid> <password>")
            return
        ok = stick.wifi_connect(args[1], args[2])
        out("connected" if ok else "failed")
        return
    if args and args[0] in ("off", "disconnect"):
        stick.wifi_disconnect()
        out("wifi off")
        return

    nets = stick.wifi_scan()
    out("%-32s %4s %3s %s" % ("ssid", "rssi", "ch", "auth"))
    for ssid, bssid, ch, rssi, auth, hidden in nets[:25]:
        name = ssid.decode() if isinstance(ssid, bytes) else ssid
        out("%-32s %4d %3d %d" % (name or "<hidden>", rssi, ch, auth))
    out("total:", len(nets))


def do_i2c(args):
    if not args or args[0] == "scan":
        out([hex(x) for x in stick.i2c_scan()])
        return
    if args[0] in ("r", "read") and len(args) >= 3:
        addr = int(args[1], 0)
        reg = int(args[2], 0)
        n = int(args[3]) if len(args) > 3 else 1
        out([hex(x) for x in stick.i2c_read(addr, reg, n)])
        return
    if args[0] in ("w", "write") and len(args) >= 4:
        stick.i2c_write(int(args[1], 0), int(args[2], 0), int(args[3], 0))
        out("ok")
        return
    out("usage: i2c [scan] | i2c r <addr> <reg> [n] | i2c w <addr> <reg> <val>")


def run(line):
    parts = line.split()
    cmd, args = parts[0].lower(), parts[1:]

    if cmd == "py":
        import machine

        exec(line[2:].strip(), {"stick": stick, "time": time, "machine": machine})
        return
    if cmd in ("help", "?"):
        out(HELP)
    elif cmd == "chip":
        do_chip()
    elif cmd == "df":
        c = stick.chip()
        out("flash: %d/%d KiB free" % (c["fs_free"], c["fs_total"]))
    elif cmd in ("bat", "batt"):
        do_bat()
    elif cmd == "temp":
        out("chip temp:", stick.temp(), "F")
    elif cmd == "imu":
        do_imu(args)
    elif cmd == "wifi":
        do_wifi(args)
    elif cmd == "i2c":
        do_i2c(args)
    elif cmd == "pins":
        a, b = stick.buttons()
        out("button A:", a, " button B:", b)
    elif cmd == "pin":
        if len(args) < 2:
            out("usage: pin <gpio> in|0|1")
        else:
            out("gpio", args[0], "=", stick.pin(int(args[0]), args[1].lower()))
    elif cmd == "adc":
        if not args:
            out("usage: adc <gpio>")
        else:
            raw, mv = stick.adc(int(args[0]))
            out("adc", args[0], "raw", raw, "~%d mV" % mv)
    elif cmd == "pwm":
        if len(args) < 2:
            out("usage: pwm <gpio> off | pwm <gpio> <freq> [duty]")
        elif args[1] == "off":
            stick.pwm(int(args[0]))
            out("pwm off")
        else:
            duty = int(args[2]) if len(args) > 2 else 512
            stick.pwm(int(args[0]), int(args[1]), duty)
            out("pwm on", args[1], "Hz duty", duty)
    elif cmd == "led":
        what = args[0] if args else "blink"
        if what == "on":
            stick.led(1)
            out("led on")
        elif what == "off":
            stick.led(0)
            out("led off")
        else:
            stick.blink(int(args[1]) if len(args) > 1 else 3)
            out("blink")
    elif cmd == "buzz":
        f = int(args[0]) if args else 2000
        ms = int(args[1]) if len(args) > 1 else 120
        stick.buzz(f, ms)
        out("buzz", f, "Hz", ms, "ms")
    elif cmd == "melody":
        stick.melody()
        out("♪")
    elif cmd == "cpu":
        import machine

        if args:
            machine.freq(int(args[0]) * 1000000)
        out("cpu:", machine.freq() // 1000000, "MHz")
    elif cmd == "sample":
        a = stick.imu()
        b = stick.battery()
        ba, bb = stick.buttons()
        out(",".join("%.3f" % x for x in a) + ",%.2f,%d,%.1f,%.1f,%d,%d,%d" % (b[0], b[1], b[2], b[3], ba, bb, stick.uptime()))
    elif cmd == "uptime":
        out("uptime:", stick.uptime(), "s")
    elif cmd == "rssi":
        if not args:
            out("usage: rssi <ssid>")
        else:
            v = stick.rssi(" ".join(args))
            out(("%s: %d dBm" % (" ".join(args), v)) if v is not None else "not found: " + " ".join(args))
    elif cmd == "bench":
        dt, s = stick.bench()
        out("200k iterations in %d ms (%.2f us/iter)" % (dt / 1000, dt / 200000))
    elif cmd == "log":
        if args and args[0] == "clear":
            for p in (LOG_PATH, "log.1"):
                try:
                    os.remove(p)
                except OSError:
                    pass
            out("log cleared")
        else:
            n = int(args[0]) if args else 30
            try:
                with open(LOG_PATH) as f:
                    lines = f.readlines()
            except OSError:
                lines = []
            for item in lines[-n:]:
                out(item.rstrip())
            out("(%d entries)" % len(lines))
    elif cmd == "deepsleep":
        secs = int(args[0]) if args else 10
        out("deepsleep", secs, "s")
        time.sleep_ms(100)
        stick.deepsleep(secs)
    elif cmd in ("reboot", "reset"):
        out("rebooting...")
        time.sleep_ms(100)
        import machine

        machine.reset()
    else:
        out("unknown command:", cmd, "- try 'help'")


def _wait_ctrl_c(ms=1200):
    """Give tools like mpremote a window to interrupt the shell on boot."""
    try:
        import select

        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        end = time.ticks_add(time.ticks_ms(), ms)
        while time.ticks_diff(end, time.ticks_ms()) > 0:
            if poll.poll(10):
                if sys.stdin.read(1) == "\x03":
                    return True
    except Exception:
        pass
    return False


def main():
    if _wait_ctrl_c():
        return
    out("")
    out("M5StickC headless shell | MicroPython " + "%d.%d.%d" % sys.implementation.version[:3])
    out("type 'help' for commands, Ctrl-C to drop to REPL")
    out("")
    while True:
        try:
            line = input("esp32> ")
        except KeyboardInterrupt:
            out("")
            break
        except EOFError:
            time.sleep_ms(50)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            run(line)
            if line != "sample" and not line.startswith("log"):
                _log(line)
        except Exception as e:
            out("error:", e)
            _log("ERR " + line + " :: " + str(e))


if __name__ == "__main__":
    main()
