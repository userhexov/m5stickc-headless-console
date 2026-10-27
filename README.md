# M5StickC без экрана → headless-консоль

У меня в руках оказался маленький красный ESP32-стик **без работающего экрана**. Прошивка Bruce на нём была бесполезна: всё управление рассчитано на LCD. Этот репозиторий — история о том, как устройство превратилось в полноценный стенд:

- **MicroPython-прошивка** с собственной командной оболочкой по serial;
- **веб-панель** с живым графиком IMU, батареей, Wi-Fi, терминалом и записью в CSV;
- **MCP-сервер** для opencode — 37 инструментов, управление платой прямо из чата с агентом;
- **три слоя логов**: на плате, в панели и audit каждого вызова MCP.

![Веб-панель](docs/img/dashboard.png)

## Что умеет

| Возможность | Как |
|---|---|
| Живой график акселерометра/гироскопа | панель, ~5 Гц, canvas без внешних библиотек |
| Батарея: напряжение, %, ток заряда/нагрузки | AXP192 по I2C |
| Кнопки A/B в реальном времени | GPIO 37/39 |
| Скан Wi-Fi с RSSI | `network.WLAN.scan()` |
| Детектор движения | jerk по акселерометру + порог |
| Запись IMU в CSV | панель, ~5 Гц, сводка min/max/mean |
| LED, бипер, мелодия | GPIO 10 / PWM 2 |
| GPIO, ADC, PWM, I2C read/write | оболочка + MCP |
| Wi-Fi connect/status/disconnect | `network.WLAN` |
| Терминал в браузере | POST `/api/cmd` |
| Управление из opencode | 37 инструментов `esp32.*` |
| Логи и аудит | плата + `events.jsonl` + `audit.jsonl` |
| Восстановление заводской прошивки | полный дамп flash |

## Быстрый старт

```bash
git clone https://github.com/userhexov/m5stickc-headless-console.git
cd m5stickc-headless-console

# 1. прошить MicroPython (стирает flash!)
./scripts/flash-micropython.sh /path/to/ESP32_GENERIC-*.bin

# 2. залить оболочку и драйверы
./scripts/deploy-device.sh

# 3. запустить панель
uv run --with pyserial python dashboard/server.py
# → http://127.0.0.1:8770

# 4. (опционально) автозапуск
./scripts/install-service.sh
```

Требования: Linux, `uv`, `python3`, USB-кабель. Всё остальное (`esptool`, `mpremote`, `pyserial`) ставится через `uvx`/`uv run` без загрязнения системы.

## Архитектура

```
┌──────────────┐   HTTP    ┌─────────────────────────┐
│ браузер      │──────────▶│  dashboard (systemd)    │
└──────────────┘           │  единственный владелец  │
┌──────────────┐   HTTP    │  /dev/ttyUSB0           │
│ opencode MCP │──────────▶│  worker-поток + очередь │
└──────────────┘           └───────────┬─────────────┘
                                       │ UART 115200
┌──────────────┐  pause/resume         ▼
│ mpremote /   │────────────────▶ ┌─────────────┐
│ esptool      │                  │  M5StickC   │
└──────────────┘                  │  MicroPython│
                                  └─────────────┘
```

Ключевая идея: **UART один**, поэтому у него должен быть один владелец. Панель держит порт открытым и обслуживает очередь команд. MCP и браузер ходят через её HTTP API. Инструменты прошивки (`mpremote`, `esptool`) на время работы просят паузу — панель закрывает порт, а после завершения открывает снова.

## Логирование

| Слой | Файл | Что пишет | Ротация |
|---|---|---|---|
| Плата | `log.txt` + `log.1` | команды и ошибки, `[uptime] cmd` | 8 КиБ |
| Панель | `~/.local/state/esp32-dashboard/events.jsonl` | команды, motion, кнопки, записи, ошибки | 1 МиБ |
| MCP | `~/.local/state/esp32-mcp/audit.jsonl` | инструмент, аргументы, ms, ok, результат | 2 МиБ |

Пароли в audit-логе редактируются (`***`). Быстрый просмотр:

```bash
./scripts/logs.sh 20          # все три слоя сразу
esp32.device_log(50)          # из opencode
esp32.audit_log(20)
```

Подробно: [docs/09-logging.md](docs/09-logging.md).

## Реальные кейсы

Готовые скрипты, проверенные на живой плате:

```bash
# блокировка экрана, когда стик перестал двигаться
IDLE_SECONDS=300 ./scripts/presence_lock.py

# две кнопки как макро-пад
BTN_A_CMD=hyprlock BTN_B_CMD='playerctl play-pause' ./scripts/macro_pad.py

# запись вибрации в CSV
./scripts/record.sh 30

# лог RSSI точки доступа
./scripts/rssi_log.py Home_2G 10 ~/rssi.csv
```

С реальными выводами и логами: [docs/08-use-cases.md](docs/08-use-cases.md).

## Структура репозитория

```
firmware/        main.py, stick.py — прошивка на плате
dashboard/       server.py + index.html — веб-панель
mcp/             MCP-сервер (37 tools) и общий слой доступа к порту
scripts/         прошивка, деплой, восстановление, presence, логи
docs/            подробная документация
```

## Документация

| Документ | О чём |
|---|---|
| [01-hardware](docs/01-hardware.md) | как опознано железо, I2C-карта, пины |
| [02-flashing](docs/02-flashing.md) | бэкап, прошивка MicroPython, возврат Bruce |
| [03-shell](docs/03-shell.md) | команды оболочки и их реализация |
| [04-dashboard](docs/04-dashboard.md) | API панели, worker, SSE, сервис |
| [05-mcp](docs/05-mcp.md) | подключение к opencode, все 37 инструментов |
| [06-pitfalls](docs/06-pitfalls.md) | 10 реальных багов и их причины |
| [07-roadmap](docs/07-roadmap.md) | presence, RSSI, CSI, автоматизации |
| [08-use-cases](docs/08-use-cases.md) | 7 кейсов с настоящими логами |
| [09-logging](docs/09-logging.md) | три слоя логов, форматы, ротация |

## Главные грабли (кратко)

1. Длинные строки в REPL **теряют байты** → короткая команда `sample` на плате.
2. `mpremote` не входит в raw REPL, если `main.py` сразу читает stdin → окно 1.2 с на Ctrl-C.
3. Гонка «панель закрыла порт / worker переоткрыл» → флаг `paused_until`.
4. MPU6886 отдаёт **big-endian** — иначе ±8 g мусора.
5. FTDI выше 115200 рвёт чтение flash.
6. AXP192 требует включить ADC (`0x82 = 0xFF`).
7. HTTP-ответ с `dict` вместо `json.dumps` → битый Content-Length.
8. Хвост промпта `esp32> ` в ответе → парсер ломается на `float`.
9. `Pin.value(1)` возвращает `None` → нельзя возвращать результат сеттера.
10. FTDI иногда теряет первые байты `sample` → один немедленный повтор.

Подробности и код — в [docs/06-pitfalls.md](docs/06-pitfalls.md).

## Ограничения

- Настоящий Wi-Fi-радар (CSI) в MicroPython недоступен — нужна C-прошивка (ESP-IDF/Arduino).
- RSSI-скан занимает 2–4 с: для presence по эфиру это медленно, но работает.
- Детектор движения сейчас по IMU (вибрация/касание), а не по отражению радиоволн.
- Порт один: панель и `mpremote repl` одновременно не живут.

## Лицензия

MIT. Делайте что хотите, только не публикуйте чужие MAC-адреса и SSID.
