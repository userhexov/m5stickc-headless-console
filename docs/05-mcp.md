# 05 · MCP: управление из opencode

MCP-сервер даёт агенту инструменты `esp32.*`, поэтому платой можно управлять прямо в чате.

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
        "ESP32_DASH": "http://127.0.0.1:8770"
      }
    }
  }
}
```

Сервер общается по stdio. После правки конфига opencode подхватывает инструменты без полного перезапуска (в этой сборке — да).

## Инструменты

| Инструмент | Аргументы | Что делает |
|---|---|---|
| `esp32.shell` | `command` | любая команда оболочки |
| `esp32.py` | `code` | Python-однострочник на плате |
| `esp32.exec_code` | `code` | многострочный код через `mpremote exec` |
| `esp32.info` | — | chip + bat + i2c |
| `esp32.reset` | — | аппаратный ресет |
| `esp32.bootlog` | `seconds` | ресет + сырой лог загрузки |
| `esp32.ls` | — | файлы на плате |
| `esp32.upload` | `local_path`, `remote_path` | залить файл |

Примеры:

```text
esp32.shell("bat")
esp32.shell("imu 5")
esp32.shell("wifi")
esp32.py("print(machine.freq())")
esp32.upload("firmware/main.py", "main.py")
```

## Как сервер сосуществует с панелью

`esp_common.run()` сначала проверяет `GET /api/ping`:

- панель жива → команда уходит `POST /api/cmd` (панель — владелец порта);
- панели нет → сервер сам открывает порт под `flock`.

Инструменты, которым нужен эксклюзив (`exec_code`, `upload`, `ls`, `reset`, `bootlog`), вызывают `POST /api/pause`, работают с портом напрямую и затем `POST /api/resume`.

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
