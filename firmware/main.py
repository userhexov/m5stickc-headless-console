# Headless M5StickC terminal shell
import sys
import time

import stick

HELP = """commands:
  help                 this text
  chip                 mcu / memory / flash info
  df                   filesystem usage
  bat                  battery: volts, %, charge/discharge mA
  temp                 chip temperature
  imu [n]              n samples of accel/gyro (default 1)
  wifi                 scan 2.4 GHz networks
  i2c                  scan i2c bus
  pins                 button states (A, B)
  led on|off|blink     red led
  buzz [hz] [ms]       beeper
  cpu [mhz]            show/set cpu frequency
  uptime               seconds since boot
  rssi <ssid>          rssi of one network (2 s scan)
  melody               play a short tune
  bench                cpu benchmark
  py <code>            run a python one-liner (stick, time available)
  reboot               restart board
"""


def out(*a):
    print(*a)


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


def do_wifi():
    nets = stick.wifi_scan()
    out("%-32s %4s %3s %s" % ("ssid", "rssi", "ch", "auth"))
    for ssid, bssid, ch, rssi, auth, hidden in nets[:25]:
        name = ssid.decode() if isinstance(ssid, bytes) else ssid
        out("%-32s %4d %3d %d" % (name or "<hidden>", rssi, ch, auth))
    out("total:", len(nets))


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
        do_wifi()
    elif cmd == "i2c":
        out([hex(x) for x in stick.i2c_scan()])
    elif cmd == "pins":
        a, b = stick.buttons()
        out("button A:", a, " button B:", b)
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
    elif cmd == "melody":
        stick.melody()
        out("♪")
    elif cmd == "bench":
        dt, s = stick.bench()
        out("200k iterations in %d ms (%.2f us/iter)" % (dt / 1000, dt / 200000))
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
    out("M5StickC headless shell | MicroPython " + "%d.%d.%d" % __import__("sys").implementation.version[:3])
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
        except Exception as e:
            out("error:", e)


if __name__ == "__main__":
    main()
