# 05 · MCP: управление из opencode

MCP-сервер даёт агенту инструменты `esp32.*`, поэтому платой можно управлять прямо в чате. Сейчас их **37**: от чтения батареи до записи регистров I2C и заливки файлов.

## Подключение

`~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "esp32": {
      "type": "local",
      "command": [
        "uv", "run", "--quiet",
        "--with", "mcp",
        "--with", "pyserial",
        "python", "/home/you/.config/opencode/mcp/esp32/server.py"
      ],
      "enabled": true,
      "environment": {
        "ESP32_PORT": "/dev/ttyUSB0",
        "ESP32_BAUD": "115200",
        "ESP32_DASH": "http://127.0.0.1:8770",
        "ESP32_MCP_STATE": "/home/you/.local/state/esp32-mcp"
      }
    }
  }
}
```

Сервер общается по stdio. После правки конфига opencode подхватывает инструменты без полного перезапуска (в этой сборке — да).

## Инструменты

### Ядро

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.shell` | `command` | любая команда оболочки |
| `esp32.py` | `code` | Python-однострочник на плате |
| `esp32.exec_code` | `code` | многострочный код через `mpremote exec` |
| `esp32.status` | — | панель, порт, uptime, батарея, motion |
| `esp32.info` | — | chip + bat + i2c |
| `esp32.battery` | — | напряжение, %, токи, статус |
| `esp32.sensors` | `n`, `delay_ms` | n отсчётов IMU |
| `esp32.buttons` | — | состояния A/B |

### Исполнительные устройства

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.led` | `state` | `on` / `off` / `blink` |
| `esp32.buzz` | `freq`, `ms` | писк |
| `esp32.melody` | — | мелодия |
| `esp32.gpio` | `pin`, `mode`, `value` | чтение/запись GPIO |
| `esp32.adc` | `pin` | raw + мВ |
| `esp32.pwm` | `pin`, `freq`, `duty` | PWM, `freq=0` — стоп |

### I2C

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.i2c_scan` | — | адреса на шине |
| `esp32.i2c_read` | `addr`, `reg`, `n` | чтение регистров |
| `esp32.i2c_write` | `addr`, `reg`, `value` | запись байта |

### Wi-Fi

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.wifi_scan` | — | скан 2.4 ГГц |
| `esp32.wifi_rssi` | `ssid` | RSSI одной сети |
| `esp32.wifi_status` | — | состояние, SSID, IP |
| `esp32.wifi_connect` | `ssid`, `password` | подключение |
| `esp32.wifi_disconnect` | — | выключить радио |

### Файлы

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.files` | — | `os.listdir()` |
| `esp32.read_file` | `path`, `max_bytes` | прочитать текст |
| `esp32.write_file` | `path`, `content` | записать (base64) |
| `esp32.remove_file` | `path` | удалить |

### Логи и запись

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.device_log` | `lines` | лог команд на плате |
| `esp32.clear_device_log` | — | стереть лог платы |
| `esp32.events` | `n` | события панели |
| `esp32.audit_log` | `n` | audit MCP-вызовов |
| `esp32.record` | `seconds` | запись IMU в CSV + сводка |

### Питание и передача

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.reboot` | — | перезагрузка |
| `esp32.reset` | — | аппаратный ресет |
| `esp32.bootlog` | `seconds` | ресет + сырой лог |
| `esp32.upload` | `local_path`, `remote_path` | залить файл |
| `esp32.download` | `remote_path`, `local_path` | скачать файл |
| `esp32.port_status` | — | порт и панель |

## Примеры

```text
esp32.status()
esp32.battery()
esp32.sensors(5)
esp32.i2c_scan()
esp32.i2c_read(0x34, 0x78, 2)      # AXP192: статус питания
esp32.gpio(10, "out", 1)           # LED
esp32.adc(36)
esp32.record(30)                   # CSV + min/max/mean
esp32.events(20)
esp32.device_log(50)
esp32.upload("firmware/main.py", "main.py")
```

Реальный диалог:

```text
esp32.status()
port: /dev/ttyUSB0
dashboard: up (http://127.0.0.1:8770)
online: True  uptime: 93s
battery: 4.02 V (80%)  charge 2.5 mA  load 0.0 mA
motion: False  score 0.015 g/s
buttons: A=1 B=1

esp32.i2c_scan()
['0x34', '0x51', '0x68']

esp32.gpio(10, "out", 1)
gpio 10 = 1
```

## Audit-лог

Каждый вызов инструмента пишется в `~/.local/state/esp32-mcp/audit.jsonl`:

```json
{"ts": 1793117299.4, "iso": "2026-10-27T23:08:19", "tool": "i2c_read",
 "args": {"addr": 52, "reg": 120, "n": 2}, "ms": 104, "ok": true,
 "error": null, "result": "['0xe4', '0x8']"}
```

- аргументы с `pass`/`secret`/`token` заменяются на `***`;
- `ms` показывает медленные вызовы;
- `result` обрезается до 500 символов;
- ротация при 2 МиБ → `audit.jsonl.1`.

Читать:

```text
esp32.audit_log(20)
```

```bash
tail -f ~/.local/state/esp32-mcp/audit.jsonl | jq .
```

## Как сервер сосуществует с панелью

`esp_common.run()` сначала проверяет `GET /api/ping`:

- панель жива → команда уходит `POST /api/cmd` (панель — владелец порта);
- панели нет → сервер сам открывает порт под `flock`.

Инструменты, которым нужен эксклюзив (`exec_code`, `upload`, `download`, `reset`, `bootlog`), вызывают `POST /api/pause`, работают с портом напрямую и затем `POST /api/resume`.

```
MCP ──ping──▶ панель ──▶ UART
MCP ──pause─▶ панель (закрыла порт)
MCP ──mpremote────────────────▶ UART
MCP ──resume▶ панель (открыла порт)
```

## Версия SDK

В `mcp` 2.x класс называется `MCPServer` и живёт в `mcp.server.mcpserver`. Старый `FastMCP` переименован, поэтому импорт:

```python
from mcp.server.mcpserver import MCPServer
```

## Отладка

```bash
# сервер можно запустить вручную и проверить, что он поднимается
uv run --with mcp --with pyserial python mcp/server.py

# проверить, видит ли панель порт
curl -s localhost:8770/api/ping
```

Если инструменты пропали из каталога — процесс MCP упал. Достаточно тронуть конфиг или перезапустить opencode; сервер поднимется заново.
