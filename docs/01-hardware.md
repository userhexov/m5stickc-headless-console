# 01 · Железо

## Как устройство было опознано

Устройство выглядит как маленький красный стик с кнопками, но **экрана нет**. Первый шаг — понять, что внутри, не разбирая корпус.

```bash
lsusb
# Bus 001 Device 004: ID 0403:6001 Future Technology Devices International, Ltd FT2232C/D/H Dual UART/FIFO IC

dmesg | tail
# ftdi_sio 1-1:1.0: FTDI USB Serial Device converter detected
# usb 1-1: Product: M5stack
# usb 1-1: Manufacturer: <redacted>
# → /dev/ttyUSB0
```

Дальше — `esptool`:

```bash
uvx --from esptool esptool --port /dev/ttyUSB0 --baud 115200 chip-id
```

```
Chip is ESP32-PICO-D4 (revision v1.1)
Features: WiFi, BT, Dual Core, 240MHz, Embedded Flash, VRef calibration in efuse
Crystal is 40MHz
MAC: xx:xx:xx:xx:xx:xx   ← затёрт в этом репозитории
Flash size: 4MB
```

По обвязке (AXP192 + PCF8563 + MPU6886) и корпусу это семейство **M5StickC / M5StickC Plus**. Точную модель без LCD не определить, но для работы это не важно: периферия одинаковая.

## I2C-карта

Шина: SDA = GPIO21, SCL = GPIO22, 400 кГц.

| Адрес | Чип | Что даёт |
|---|---|---|
| `0x34` | AXP192 | питание, заряд, кнопка питания, LCD-питание |
| `0x51` | PCF8563 | RTC |
| `0x68` | MPU6886 | акселерометр + гироскоп |

Проверка:

```python
import stick
print([hex(x) for x in stick.i2c_scan()])
# ['0x34', '0x51', '0x68']
```

## Используемые пины

| GPIO | Что |
|---|---|
| 21 / 22 | I2C SDA / SCL |
| 10 | красный LED |
| 2 | бипер (PWM) |
| 37 | кнопка A |
| 39 | кнопка B |
| 9 | ИК-передатчик (не используется) |

Кнопки читаются как `Pin.IN`; нажатие = `0`, отпущено = `1`.

## Питание

AXP192 отдаёт напряжение и токи:

- `0x78` — напряжение батареи (12 бит, шаг 1.1 мВ);
- `0x7A` — ток заряда (шаг 0.5 мА);
- `0x7C` — ток разряда (13 бит, шаг 0.5 мА);
- `0x00` — статус (бит 2 — «charging»).

Перед чтением нужно включить ADC:

```python
i2c.writeto_mem(0x34, 0x82, b"\xff")
```

Батарея у устройства маленькая (~95 мА·ч), поэтому практический режим — питание от USB. При отключении кабеля стик живёт минуты, а не часы.

## Почему не экран

Экран не используется вообще: ни один сценарий не зависит от LCD. Вся индикация — браузер и serial. Это и стало главной идеей проекта.
