# 03 · Оболочка на плате

`main.py` — это не просто скрипт, а маленькая REPL-оболочка с промптом `esp32> `.

## Как она стартует

```python
def main():
    if _wait_ctrl_c():      # окно для mpremote
        return
    ...
    while True:
        try:
            line = input("esp32> ")
        except KeyboardInterrupt:
            break           # Ctrl-C → обычный REPL
        except EOFError:
            continue        # случайный EOT не должен убивать оболочку
        run(line)
```

`_wait_ctrl_c()` в течение 1.2 с слушает stdin через `select.poll()`. Если пришёл `\x03`, оболочка не запускается — плата остаётся в REPL, и `mpremote` может войти в raw REPL. Это компромисс: 1.2 с задержки при загрузке против рабочего `mpremote`.

## Команды

| Команда | Что делает |
|---|---|
| `help` | список команд |
| `chip` | MicroPython, частота, UID, RAM, flash |
| `df` | свободное место |
| `bat` | напряжение, %, токи, статус AXP192 |
| `temp` | температура чипа (°F, так отдаёт `esp32.raw_temperature`) |
| `imu [n]` | n отсчётов акселерометра и гироскопа |
| `wifi` | скан 2.4 ГГц, сортировка по RSSI |
| `rssi <ssid>` | RSSI одной сети |
| `i2c` | скан шины |
| `pins` | состояния кнопок A/B |
| `led on\|off\|blink` | красный LED |
| `buzz [hz] [ms]` | бипер |
| `melody` | короткая мелодия |
| `bench` | бенчмарк цикла |
| `cpu [mhz]` | показать/сменить частоту |
| `uptime` | секунды с загрузки |
| `sample` | служебная CSV-строка для панели |
| `py <code>` | выполнить Python на плате |
| `reboot` | перезагрузка |

## `py` и пространство имён

```python
exec(line[2:].strip(), {"stick": stick, "time": time, "machine": machine})
```

Доступны `stick`, `time`, `machine`. Примеры:

```text
esp32> py print(machine.freq())
160000000
esp32> py print(stick.chip()["mem_free"])
96800
esp32> py print(stick.imu())
(-0.14, -0.05, -0.9, 3.8, 1.9, 14.6)
```

Важно: `exec` с отдельным словарём ломает некоторые конструкции (генераторы внутри comprehension в CPython; в MicroPython ведёт себя иначе). Для сложного используйте `exec_code` через MCP — он гоняет многострочный код через `mpremote exec`.

## `sample` — почему отдельная команда

Панель опрашивает плату ~5 раз в секунду. Если каждый раз гнать длинную строку `py a=stick.imu();b=stick.battery();...`, на 115200 начинают теряться байты (см. [06-pitfalls](06-pitfalls.md)). Поэтому на плате живёт короткая команда:

```python
elif cmd == "sample":
    a = stick.imu()
    b = stick.battery()
    ba, bb = stick.buttons()
    out(",".join("%.3f" % x for x in a) + ",%.2f,%d,%.1f,%.1f,%d,%d,%d" %
        (b[0], b[1], b[2], b[3], ba, bb, stick.uptime()))
```

Формат (13 полей):

```
ax,ay,az,gx,gy,gz,volts,pct,charge,load,btnA,btnB,uptime
```

## Как добавить команду

1. В `stick.py` — функция-помощник (драйвер).
2. В `main.py`, в `run()` — ветка `elif cmd == "..."`.
3. В `HELP` — строка описания.

Пример:

```python
# stick.py
def hello():
    return "hi from " + machine.unique_id().hex()

# main.py
elif cmd == "hello":
    out(stick.hello())
```

## Ограничения оболочки

- Нет истории и редактирования строки — это `input()`, а не readline.
- Вывод не буферизуется: длинные ответы может обрезать таймаут хоста.
- `Ctrl-C` выходит в REPL; обратно — `Ctrl-D` (soft reset) или `mpremote reset`.
