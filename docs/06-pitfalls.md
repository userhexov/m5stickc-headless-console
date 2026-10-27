# 06 · Грабли: 8 багов и их причины

Это самая полезная часть репозитория. Почти каждый баг выглядел как «магия», пока не находилась причина.

## 1. Длинные команды теряют байты

**Симптом.** Панель периодически получала `error: invalid syntax` или ответ с пропущенными символами:

```
py astck.imu(;b=tick.battery();print('
```

**Причина.** Строка на 150+ символов при частой отправке (5 Гц) не успевает обрабатываться REPL MicroPython: часть байт теряется во входном буфере.

**Решение.** Не гонять длинный код. На плате появилась короткая команда `sample` (7 байт), которая печатает готовый CSV.

```python
elif cmd == "sample":
    ...
```

**Вывод.** Чем короче строка в REPL — тем надёжнее. Логику переносите на устройство.

## 2. mpremote не входит в raw REPL

**Симптом.**

```
mpremote.transport.TransportError: could not enter raw repl
```

**Причина.** `main.py` стартует сразу после reset и блокируется в `input()`. `mpremote` посылает Ctrl-C/Ctrl-A, но оболочка уже захватила stdin.

**Решение.** Окно 1.2 с на Ctrl-C при старте:

```python
def _wait_ctrl_c(ms=1200):
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    end = time.ticks_add(time.ticks_ms(), ms)
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if poll.poll(10) and sys.stdin.read(1) == "\x03":
            return True
    return False
```

**Цена.** 1.2 с задержки при каждой загрузке. Зато `mpremote`, `esptool` и `upload` работают предсказуемо.

## 3. Гонка pause / close

**Симптом.** Во время `mpremote cp` — `could not enter raw repl`, хотя панель «на паузе».

**Причина.** Панель закрывала порт по `/api/pause`, но worker в этот момент уже выполнял `_write_read()` и успевал **переоткрыть** порт:

```python
def _write_read(...):
    if self.ser is None:
        self._open()      # ← вот здесь гонка
```

**Решение.** Флаг `paused_until` проверяется и в `exec()`, и в `_write_read()`; после закрытия — пауза 0.4 с, чтобы in-flight запись осела.

```python
def pause(self, seconds=20.0):
    self.paused_until = time.time() + seconds
    self._close()
    time.sleep(0.4)
```

## 4. MPU6886 — big-endian

**Симптом.** Акселерометр показывает ±8 g в покое, график «пляшет».

**Причина.** Данные читаются как little-endian, а MPU6886 отдаёт **big-endian**:

```python
v = (d[i] << 8) | d[i + 1]      # правильно
# v = d[i] | (d[i+1] << 8)      # неправильно
```

**Решение.** `s16()` собирает старший байт первым. После фикса в покое: `~-0.03 / -0.06 / -0.89 g`.

## 5. FTDI выше 115200 рвёт flash

**Симптом.** `esptool` на `230400`/`460800` падает или читает мусор.

**Причина.** Конкретный мост `0403:6001` (FT2232) не держит высокие скорости в этой схеме.

**Решение.** Всегда `--baud 115200`. Медленнее, но надёжно.

## 6. AXP192 без включения ADC

**Симптом.** Напряжение батареи — нули или случайные значения.

**Причина.** ADC-каналы выключены по умолчанию.

**Решение.**

```python
i2c.writeto_mem(0x34, 0x82, b"\xff")   # включить все ADC
```

## 7. HTTP-ответ с dict

**Симптом.** `POST /api/cmd` возвращает `Content-Length: 2` и тело `HT`.

**Причина.** В `_send()` передали `dict` вместо строки: `len(dict)` = число ключей, а `wfile.write(dict)` падает.

**Решение.** Всегда `json.dumps(...)`:

```python
self._send(200, json.dumps({"ok": True, "output": out}))
```

## 8. Хвост промпта в ответе

**Симптом.** Редко: `could not convert string to float: "esp32> -0.134"`.

**Причина.** Между командами в буфере оставался предыдущий промпт; парсер получал его в начале строки.

**Решение.** `clean()` вырезает **все** вхождения промпта, а не только последний:

```python
text = raw.decode(...).replace("\r", "").replace("esp32> ", "")
```

## 9. `Pin.value(1)` возвращает `None`

**Симптом.** `esp32.gpio(10, "out", 1)` печатает `gpio 10 = None`, хотя LED загорается.

**Причина.** В MicroPython сеттер `Pin.value(v)` ничего не возвращает. Обёртка возвращала результат сеттера.

**Решение.** Выставить и вернуть значение явно:

```python
def pin(num, mode):
    p = machine.Pin(int(num), machine.Pin.IN if mode == "in" else machine.Pin.OUT)
    if mode == "in":
        return p.value()
    v = 1 if mode in ("1", "on", "high") else 0
    p.value(v)
    return v
```

## 10. FTDI теряет первые байты короткой команды

**Симптом.** Редко (2 раза за ~10 минут): в логе `bad sample: 'smple\n-0.137'`, плата отвечает `unknown command: smple`.

**Причина.** Мост FT2232 изредка «съедает» 1–2 первых байта строки, если писать сразу после `reset_input_buffer()`. Команда `sample` превращается в `smple`.

**Решение.** Один немедленный повтор в `_sample()`. Частота 5 Гц не страдает, в лог попадает только двойная неудача:

```python
for _attempt in (1, 2):
    raw = self._write_read(SAMPLE, timeout=6)
    parts = [p for p in raw.strip().split(",") if p]
    if len(parts) >= 13:
        try:
            vals = [float(p) for p in parts[:13]]
            break
        except ValueError:
            pass
```

## Бонус: почему панель — владелец порта

Открытие/закрытие `serial.Serial` на каждый запрос — источник гонок и потерь. Один долгоживущий владелец + очередь + `pause/resume` для прошивки оказались единственной схемой, которая стабильно держит 5 Гц телеметрии и параллельный `mpremote`.
