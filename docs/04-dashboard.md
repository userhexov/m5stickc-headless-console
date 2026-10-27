# 04 · Веб-панель

```
uv run --with pyserial python dashboard/server.py
# → http://127.0.0.1:8770
```

Панель — это один процесс на стандартной библиотеке плюс `pyserial`. Никаких CDN, никакого интернета: HTML/CSS/JS лежат в `index.html`, график рисуется на `<canvas>` вручную.

## Почему панель владеет портом

UART — эксклюзивный ресурс. Если открывать/закрывать его на каждый запрос, начинаются потери байт и гонки с `mpremote`. Поэтому:

- панель держит `serial.Serial` открытым всё время;
- все команды идут через **очередь** в один worker-поток;
- команды пользователя имеют приоритет над опросом телеметрии;
- `mpremote`/`esptool` просят паузу через API.

```
HTTP /api/cmd ──┐
опрос 5 Гц ─────┼──▶ queue ──▶ worker ──▶ UART ──▶ плата
                │                 │
                └──── SSE ◀───────┘ состояние
```

## API

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| GET | `/` | — | HTML |
| GET | `/api/state` | — | снимок состояния |
| GET | `/api/ping` | — | `{"ok": true, "state_dir": ...}` |
| GET | `/api/logs?n=100` | — | хвост `events.jsonl` |
| GET | `/api/device-log?n=50` | — | вывод `log N` с платы |
| GET | `/api/recordings` | — | список CSV-записей |
| GET | `/events` | — | SSE-поток состояния, 5 Гц |
| POST | `/api/cmd` | `{"command": "bat"}` | `{"ok": true, "output": "...", "ms": 87}` |
| POST | `/api/wifi` | `{}` | запускает скан асинхронно |
| POST | `/api/motion` | `{"threshold": 0.06}` | меняет порог |
| POST | `/api/record` | `{"seconds": 10}` | блокирующая запись + сводка |
| POST | `/api/pause` | `{"seconds": 30}` | закрывает порт для прошивки |
| POST | `/api/resume` | `{}` | открывает порт снова |

Примеры:

```bash
curl -s localhost:8770/api/state | jq
curl -s -X POST localhost:8770/api/cmd \
  -H 'Content-Type: application/json' \
  -d '{"command":"bat"}'
curl -s "localhost:8770/api/logs?n=20" | jq '.entries[0]'
```

## Состояние

```json
{
  "online": true,
  "imu": [-0.14, -0.05, -0.9, 3.8, 1.9, 14.6],
  "volts": 3.92, "pct": 68,
  "charge": 2.5, "load": 0.0,
  "btn": [1, 1],
  "uptime": 118,
  "motion": false, "score": 0.01,
  "wifi": [{"ssid": "...", "rssi": -42, "ch": 6}],
  "events": [{"t": "22:47:01", "text": "wifi scan: 14 networks", "kind": "wifi"}],
  "recording": false,
  "last_recording": {"name": "imu-20261027-230857.csv", "rows": 10, "spread_g": 0.014},
  "host_uptime": 920
}
```

## Детектор движения

Считается «рывок» между соседними отсчётами:

```python
jerk = sqrt((ax-ax0)² + (ay-ay0)² + (az-az0)²)
score = 0.75 * score + 0.25 * jerk     # EMA
moving = score > threshold             # по умолчанию 0.06 g
```

Порог регулируется ползунком. При переходе `False → True` в лог пишется событие. Это детектор **вибрации/касания**, а не радиолокатор: стик должен стоять на столе, а вы — топать рядом или трогать корпус.

## Кнопки

Состояния `btn` приходят в каждом `sample`. Панель сравнивает с предыдущим значением и пишет в лог:

```text
2026-10-27T23:12:04  button  button A pressed
2026-10-27T23:12:04  button  button A released
```

Это же событие уходит вебхуку (если он задан). Скрипт `scripts/macro_pad.py` читает `/api/state` и превращает нажатия в команды хоста.

## Запись IMU в CSV

`POST /api/record {"seconds": 10}` блокирует HTTP-запрос на время записи и возвращает сводку:

```json
{
  "ok": true,
  "name": "imu-20261027-230857.csv",
  "rows": 10,
  "seconds": 2.0,
  "mean_g": 0.891,
  "min_g": 0.883,
  "max_g": 0.897,
  "spread_g": 0.014
}
```

Данные берутся из уже обновляемого состояния (~5 Гц), поэтому запись **не нагружает UART** дополнительными командами. Файлы лежат в `~/.local/state/esp32-dashboard/recordings/`.

Колонки:

```csv
t,ax,ay,az,gx,gy,gz,volts,pct,btnA,btnB
0.00,-0.145,-0.060,-0.884,3.8,1.9,14.6,4.02,80,1,1
```

В UI это кнопка **record 10s**; из MCP — `esp32.record(30)`; из shell — `./scripts/record.sh 30`.

## Логи панели

Все события пишутся в `~/.local/state/esp32-dashboard/events.jsonl` (ротация 1 МиБ → `.1`):

```json
{"ts": 1793117216.5, "iso": "2026-10-27T23:06:56", "kind": "cmd",
 "text": "cmd: pin 10 1", "ms": 89, "ok": true}
```

Типы: `system`, `cmd`, `motion`, `button`, `wifi`, `record`, `config`, `error`. Запись идёт под `threading.Lock`, поэтому параллельные HTTP-запросы не рвут строки.

Читать:

```bash
curl -s "localhost:8770/api/logs?n=50"
./scripts/logs.sh 50
```

Подробно про все три слоя — [09-logging](09-logging.md).

## Вебхук

Если задан `ESP32_WEBHOOK`, события `motion` и `button` отправляются POST-ом:

```bash
ESP32_WEBHOOK=http://127.0.0.1:9000/hook ./scripts/install-service.sh
```

Payload:

```json
{"event": "motion", "kind": "motion", "text": "motion detected (0.12 g/s)", "score": 0.12}
```

Доставка идёт в отдельном потоке с таймаутом 3 с; ошибка попадает в `events.jsonl` как `kind=error`.

## Wi-Fi скан

`wifi` на плате занимает 2–4 с. Панель запускает его в отдельном потоке, чтобы не блокировать UI, и складывает результат в состояние. При старте скан выполняется автоматически через 2 с.

## systemd --user

```bash
./scripts/install-service.sh
systemctl --user status esp32-dashboard
journalctl --user -u esp32-dashboard -f
```

Юнит пишется с абсолютными путями текущего репозитория. После перезагрузки/логина панель поднимется сама.

## Переменные окружения

| Переменная | По умолчанию |
|---|---|
| `ESP32_PORT` | `/dev/ttyUSB0` |
| `ESP32_BAUD` | `115200` |
| `DASH_PORT` | `8770` |
| `ESP32_DASH` | `http://127.0.0.1:8770` |
| `ESP32_LOCK` | `$TMPDIR/esp32-port.lock` |
| `ESP32_STATE_DIR` | `~/.local/state/esp32-dashboard` |
| `ESP32_WEBHOOK` | пусто (выключен) |

## Если панель не отвечает

```bash
ss -ltnp | grep 8770          # кто держит порт
systemctl --user restart esp32-dashboard
journalctl --user -u esp32-dashboard -n 50 --no-pager
```

Частая причина — устройство перезагрузилось или отключено: worker закроет порт и будет переоткрывать его с задержкой, в логе появятся `serial error`.
