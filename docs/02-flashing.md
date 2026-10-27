# 02 · Прошивка

## Правило №1: сначала бэкап

Любая запись во flash стирает всё. Полный дамп 4 МБ снимается до любых действий:

```bash
systemctl --user stop esp32-dashboard 2>/dev/null || true

uvx --from esptool esptool \
  --port /dev/ttyUSB0 --baud 115200 \
  read-flash 0 4MB ~/esp32-backup/m5stick-full-4MB.bin

sha256sum ~/esp32-backup/m5stick-full-4MB.bin
```

Внутри дампа была прошивка **Bruce** (Arduino/ESP-IDF 4.4). Она сохранена и проверена побайтово.

## Прошивка MicroPython

```bash
uvx --from esptool esptool --port /dev/ttyUSB0 --baud 115200 erase-flash

uvx --from esptool esptool --port /dev/ttyUSB0 --baud 115200 \
  write-flash 0x1000 ESP32_GENERIC-20260824-v1.29.0.bin
```

Почему `0x1000`: у ESP32 загрузчик занимает первые 4 КБ, образ MicroPython пишется сразу за ним. Для ESP32 (не S3/C3) это стандартный offset.

Проверка:

```bash
uvx mpremote connect /dev/ttyUSB0 exec \
  "import sys; print(sys.implementation)"
```

```
(name='micropython', version=(1, 29, 0), ...)
```

## Загрузка оболочки

```bash
uvx mpremote connect /dev/ttyUSB0 cp firmware/stick.py :stick.py
uvx mpremote connect /dev/ttyUSB0 cp firmware/main.py :main.py
uvx mpremote connect /dev/ttyUSB0 reset
```

Или просто:

```bash
./scripts/deploy-device.sh
```

Скрипт сам попросит панель освободить порт.

## Возврат Bruce

```bash
systemctl --user stop esp32-dashboard
uvx --from esptool esptool --port /dev/ttyUSB0 --baud 115200 \
  write-flash 0 ~/esp32-backup/m5stick-full-4MB.bin
```

## Почему только 115200

На этом FTDI-мосте (`0403:6001`) попытки `230400`/`460800` приводят к обрывам при чтении flash. Ошибка выглядит как «A fatal error occurred: Failed to connect» или рваные данные. На `115200` всё стабильно, хоть и медленнее (полный дамп ~5 минут).

## Если mpremote не входит в raw REPL

Симптом:

```
mpremote.transport.TransportError: could not enter raw repl
```

Причина — `main.py` на плате сразу захватывает stdin. В прошивке есть окно 1.2 с на Ctrl-C при старте (`_wait_ctrl_c`), поэтому `mpremote` успевает перехватить управление. Если проблема осталась:

```bash
# панель держит порт?
systemctl --user stop esp32-dashboard
# или вручную: отправить Ctrl-C и затем команду
```

## Если порт занят

```
could not open port /dev/ttyUSB0: Device or resource busy
```

Порт может держать панель или старый процесс MCP:

```bash
ss -ltnp | grep 8770
systemctl --user stop esp32-dashboard
pkill -f 'esp32/server[.]py'
```
