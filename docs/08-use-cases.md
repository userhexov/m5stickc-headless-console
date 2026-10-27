# 08 · Реальные кейсы

Все примеры ниже — настоящие выводы с этого устройства, а не выдуманные. SSID заменён на `Home_2G`.

## 1. Presence → блокировка экрана

Стик лежит на столе. Пока вы рядом и двигаетесь — таймер сбрасывается. Ушли — через N секунд вызывается `hyprlock`.

```bash
IDLE_SECONDS=300 LOCK_CMD=hyprlock ./scripts/presence_lock.py
```

Проверка с коротким порогом:

```text
23:08:59 presence: idle=3s poll=2.0s lock=echo LOCKED
23:09:03 idle 4s -> echo LOCKED
LOCKED
```

Как systemd-сервис:

```bash
./scripts/install-presence-service.sh
systemctl --user enable --now esp32-presence
journalctl --user -u esp32-presence -f
```

Почему по IMU, а не по Wi-Fi: скан Wi-Fi занимает 2–4 с и шумит на ±5 дБ, а вибрация стола от шагов и касаний даёт мгновенную реакцию. Для «ушёл из-за стола» этого достаточно.

## 2. Макро-пад на две кнопки

```bash
BTN_A_CMD='hyprlock' BTN_B_CMD='playerctl play-pause' ./scripts/macro_pad.py
```

```text
macro pad: A='hyprlock' B='playerctl play-pause'
23:12:04 press A -> hyprlock
23:12:19 press B -> playerctl play-pause
```

События кнопок при этом пишутся в лог панели:

```text
2026-10-27T23:12:04  button  button A pressed
2026-10-27T23:12:04  button  button A released
```

## 3. Запись вибрации в CSV

```bash
./scripts/record.sh 2
```

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

Файл: `~/.local/state/esp32-dashboard/recordings/imu-20261027-230857.csv`

```csv
t,ax,ay,az,gx,gy,gz,volts,pct,btnA,btnB
0.00,-0.145,-0.060,-0.884,3.8,1.9,14.6,4.02,80,1,1
0.20,-0.147,-0.058,-0.886,4.1,2.0,15.0,4.02,80,1,1
```

Что с этим делать:

- сравнить `spread_g` в покое и при ходьбе рядом;
- поймать «кто трогал стик» (spread резко растёт);
- откалибровать порог детектора движения.

## 4. Лог RSSI точки доступа

```bash
./scripts/rssi_log.py Home_2G 5 ~/rssi.csv
```

```text
logging 'Home_2G' every 5.0s -> /home/you/rssi.csv
23:09:09 -44 dBm
23:09:18 -45 dBm
```

```csv
iso,ssid,rssi
2026-10-27T23:09:09,Home_2G,-44
2026-10-27T23:09:18,Home_2G,-45
```

Интервал меньше 5 с бессмысленен: сам скан занимает 2–4 с. Для presence по эфиру нужен режим station и CSI (см. [07-roadmap](07-roadmap.md)).

## 5. Watchdog питания

```bash
while true; do
  curl -s localhost:8770/api/state | python3 -c '
import json,sys
s=json.load(sys.stdin)
print(s["volts"], s["pct"], s["charge"], s["load"])'
  sleep 30
done
```

Реальный вывод:

```text
4.02 80 2.5 0.0
4.02 80 2.5 0.0
```

Если `charge` падает до нуля, а `pct` ползёт вниз — кабель отвалился. Можно повесить `notify-send` на `pct < 20`.

## 6. Агентное управление через MCP

Запрос агенту: «проверь, что на I2C, и мигни светодиодом».

Агент вызывает:

```text
esp32.status()      → dashboard: up, online: True, battery 4.02 V
esp32.i2c_scan()    → ['0x34', '0x51', '0x68']
esp32.i2c_read(0x34, 0x78, 2) → ['0xe4', '0x8']
esp32.gpio(10, "out", 1)      → gpio 10 = 1
esp32.gpio(10, "out", 0)      → gpio 10 = 0
```

Всё это оседает в audit-логе:

```text
2026-10-27T23:08:19  i2c_read       104ms  ok
2026-10-27T23:08:19  gpio           144ms  ok
2026-10-27T23:08:20  gpio           145ms  ok
```

## 7. «Кто трогал стик»

1. `./scripts/record.sh 30` в пустой комнате → `spread_g ≈ 0.02`.
2. Выйти, попросить кого-то коснуться стика.
3. Повторить запись → `spread_g` вырастет в разы, в логе появится `motion detected`.

Событие также уходит вебхуку, если задан `ESP32_WEBHOOK`:

```bash
ESP32_WEBHOOK=http://127.0.0.1:9000/hook ./dashboard/server.py
```

Payload:

```json
{"event": "motion", "kind": "motion", "text": "motion detected (0.12 g/s)", "score": 0.12}
```
