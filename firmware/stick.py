# M5StickC headless helpers (MicroPython)
import machine
import time

I2C = machine.I2C(0, sda=machine.Pin(21), scl=machine.Pin(22), freq=400000)

AXP192 = 0x34
PCF8563 = 0x51
MPU6886 = 0x68

LED_PIN = 10
BUZZ_PIN = 2
IR_PIN = 9
BTN_A = 37
BTN_B = 39


def _r(addr, reg, n=1):
    return I2C.readfrom_mem(addr, reg, n)


def _w(addr, reg, val):
    I2C.writeto_mem(addr, reg, bytes([val]))


# ---------- power ----------
def axp_init():
    _w(AXP192, 0x82, 0xFF)  # enable ADC channels


def battery():
    axp_init()
    h, l = _r(AXP192, 0x78, 2)
    volts = ((h << 4) | (l & 0x0F)) * 1.1 / 1000.0
    chg_ma = _r(AXP192, 0x7A)[0] * 0.5
    d = _r(AXP192, 0x7C, 2)
    dis_ma = ((d[0] << 5) | (d[1] & 0x1F)) * 0.5
    status = _r(AXP192, 0x00)[0]
    pct = int((volts - 3.3) / 0.9 * 100)
    pct = max(0, min(100, pct))
    return volts, pct, chg_ma, dis_ma, status


# ---------- imu ----------
def imu_init():
    who = _r(MPU6886, 0x75)[0]
    _w(MPU6886, 0x6B, 0x80)  # soft reset
    time.sleep_ms(60)
    _w(MPU6886, 0x6B, 0x01)  # wake, PLL clock source
    _w(MPU6886, 0x6C, 0x00)  # enable accel + gyro
    _w(MPU6886, 0x19, 0x07)  # sample rate divider
    _w(MPU6886, 0x1A, 0x03)  # DLPF
    _w(MPU6886, 0x1C, 0x10)  # +-8 g
    _w(MPU6886, 0x1B, 0x18)  # +-2000 dps
    time.sleep_ms(50)
    return who


def imu():
    d = _r(MPU6886, 0x3B, 14)

    def s16(i):
        v = (d[i] << 8) | d[i + 1]  # MPU6886 is big-endian
        return v - 65536 if v & 0x8000 else v

    return (
        s16(0) / 4096.0,
        s16(2) / 4096.0,
        s16(4) / 4096.0,
        s16(8) / 16.4,
        s16(10) / 16.4,
        s16(12) / 16.4,
    )


# ---------- io ----------
def led(state):
    machine.Pin(LED_PIN, machine.Pin.OUT).value(1 if state else 0)


def blink(times=3, ms=150):
    p = machine.Pin(LED_PIN, machine.Pin.OUT)
    for _ in range(times):
        p.value(1)
        time.sleep_ms(ms)
        p.value(0)
        time.sleep_ms(ms)


def buzz(freq=2000, ms=120, duty=300):
    p = machine.PWM(machine.Pin(BUZZ_PIN), freq=freq, duty=duty)
    time.sleep_ms(ms)
    p.deinit()
    machine.Pin(BUZZ_PIN, machine.Pin.OUT).value(0)


def buttons():
    return machine.Pin(BTN_A, machine.Pin.IN).value(), machine.Pin(BTN_B, machine.Pin.IN).value()


# ---------- radio ----------
def wifi_scan():
    import network

    w = network.WLAN(network.STA_IF)
    if not w.active():
        w.active(True)
    time.sleep(0.8)
    nets = w.scan()
    nets.sort(key=lambda x: -x[3])
    return nets


def i2c_scan():
    return I2C.scan()


def chip():
    import gc
    import os
    import sys

    st = os.statvfs("/")
    return {
        "mpy": "%d.%d.%d" % sys.implementation.version[:3],
        "freq": machine.freq(),
        "uid": machine.unique_id().hex(),
        "mem_free": gc.mem_free(),
        "fs_total": st[0] * st[2] // 1024,
        "fs_free": st[0] * st[3] // 1024,
    }


def temp():
    try:
        import esp32

        return esp32.raw_temperature()
    except Exception:
        return None


# ---------- extras ----------
BOOT_MS = time.ticks_ms()


def uptime():
    return time.ticks_diff(time.ticks_ms(), BOOT_MS) // 1000


def rssi(ssid):
    best = None
    for net in wifi_scan():
        name = net[0].decode() if isinstance(net[0], bytes) else net[0]
        if name == ssid:
            if best is None or net[3] > best:
                best = net[3]
    return best


def melody():
    for f, ms in ((659, 110), (622, 110), (659, 110), (494, 110), (587, 110), (523, 110), (440, 220)):
        buzz(f, ms, 350)


def bench():
    t0 = time.ticks_us()
    s = 0
    for i in range(200000):
        s = (s + i * i) & 0xFFFF
    dt = time.ticks_diff(time.ticks_us(), t0)
    return dt, s
