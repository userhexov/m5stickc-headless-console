# 09 · Логирование

Логов три слоя, и это не дублирование: каждый отвечает на свой вопрос.

| Слой | Файл | Отвечает на вопрос | Ротация |
|---|---|---|---|
| Плата | `log.txt` (+ `log.1`) | что выполнялось на устройстве | 8 КиБ |
| Панель | `~/.local/state/esp32-dashboard/events.jsonl` | что происходило в системе | 1 МиБ |
| MCP | `~/.local/state/esp32-mcp/audit.jsonl` | кто и что вызывал через агента | 2 МиБ |

## 1. Плата: `log.txt`

Оболочка пишет каждую команду (кроме `sample` и `log`) и каждую ошибку:

```text
[72s] i2c
[72s] i2c r 52 120 2
[73s] py import os;print(os.listdir())
[96s] pin 10 1
[97s] pin 10 0
```

Формат: `[uptime] команда`. Времени как такового нет — RTC не синхронизирован, а uptime честнее, чем ничего.

Ротация: при размере > 8 КиБ файл переименовывается в `log.1` (старый `log.1` удаляется). Итого максимум ~16 КиБ флеша.

Чтение:

```text
esp32> log 20
esp32> log clear
```

Через MCP:

```text
esp32.device_log(50)
esp32.clear_device_log()
```

Через API:

```bash
curl -s "localhost:8770/api/device-log?n=20"
```

## 2. Панель: `events.jsonl`

Каждая строка — JSON:

```json
{"ts": 1793117216.5, "iso": "2026-10-27T23:06:56", "kind": "record",
 "text": "recording imu-20261027-230653.csv: 15 rows, spread 0.029 g",
 "path": "/home/you/.local/state/esp32-dashboard/recordings/imu-20261027-230653.csv",
 "rows": 15}
```

Типы событий (`kind`):

- `system` — старт панели;
- `cmd` — команда через API, с `ms` и `ok`;
- `motion` — сработал детектор, со `score`;
- `button` — нажатие/отпускание A/B;
- `wifi` — результаты скана;
- `record` — запись CSV;
- `config` — смена порога;
- `error` — ошибки serial/вебхука/команд.

Пример реального файла:

```text
2026-10-27T23:06:40  system  dashboard started on port 8770
2026-10-27T23:06:47  wifi    wifi scan: 12 networks
2026-10-27T23:06:47  cmd     cmd: pin 10 1
2026-10-27T23:06:56  record  recording imu-20261027-230653.csv: 15 rows, spread 0.029 g
```

Ротация: > 1 МиБ → `events.jsonl.1`. Пишется под `threading.Lock`, поэтому параллельные запросы не рвут строки.

Чтение:

```bash
curl -s "localhost:8770/api/logs?n=50"
./scripts/logs.sh 50
```

Вебхук: если задан `ESP32_WEBHOOK`, события `motion` и `button` отправляются POST-ом с JSON. Ошибки доставки попадают в лог как `kind=error`.

## 3. MCP: `audit.jsonl`

Каждый вызов инструмента:

```json
{"ts": 1793117299.4, "iso": "2026-10-27T23:08:19", "tool": "i2c_read",
 "args": {"addr": 52, "reg": 120, "n": 2}, "ms": 104, "ok": true,
 "error": null, "result": "['0xe4', '0x8']"}
```

Что важно:

- **пароли редактируются**: аргументы с `pass`/`secret`/`token` заменяются на `***`;
- `ms` — длительность, видно медленные вызовы;
- `result` обрезается до 500 символов;
- ошибки пишутся с `ok: false` и текстом.

Чтение:

```text
esp32.audit_log(20)
```

```bash
tail -f ~/.local/state/esp32-mcp/audit.jsonl | jq .
```

## Почему не syslog

Панель и MCP запускаются как пользовательские процессы и могут работать без root. XDG-путь `~/.local/state/...` переживает перезапуски, не требует прав и легко архивируется. Systemd-сервисы дополнительно пишут stdout в journal — там видны падения и трейсбеки:

```bash
journalctl --user -u esp32-dashboard -n 50
journalctl --user -u esp32-presence -f
```

## Что НЕ логируется

- `sample` — 5 Гц опрос, иначе лог платы умрёт за минуту;
- `log` — иначе чтение лога порождает записи в лог;
- содержимое Wi-Fi пароля — только факт подключения.

## Диагностика по логам

| Симптом | Где смотреть |
|---|---|
| панель «онлайн», но данных нет | `events.jsonl`, `kind=error` |
| команда выполняется долго | audit `ms` |
| устройство перезагружалось | device log: uptime сбрасывается |
| кто-то дёргал GPIO | device log + MCP audit |
| пропал Wi-Fi | `kind=wifi` и `kind=error` |
