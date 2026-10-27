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
| GET | `/api/ping` | — | `{"ok": true}` |
| GET | `/events` | — | SSE-поток состояния, 5 Гц |
| POST | `/api/cmd` | `{"command": "bat"}` | `{"ok": true, "output": "..."}` |
| POST | `/api/wifi` | `{}` | запускает скан асинхронно |
| POST | `/api/motion` | `{"threshold": 0.06}` | меняет порог |
| POST | `/api/pause` | `{"seconds": 30}` | закрывает порт для прошивки |
| POST | `/api/resume` | `{}` | открывает порт снова |

Примеры:

```bash
curl -s localhost:8770/api/state | jq
curl -s -X POST localhost:8770/api/cmd \
  -H 'Content-Type: application/json' \
  -d '{"command":"bat"}'
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
  "events": [{"t": "22:47:01", "text": "wifi scan: 14 networks"}]
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

## Если панель не отвечает

```bash
ss -ltnp | grep 8770          # кто держит порт
systemctl --user restart esp32-dashboard
journalctl --user -u esp32-dashboard -n 50 --no-pager
```

Частая причина — устройство перезагрузилось или отключено: worker закроет порт и будет переоткрывать его с задержкой, в логе появятся `serial error`.
