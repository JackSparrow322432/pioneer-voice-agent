# Разбор проблем

Реальные проблемы, которые встретились при запуске, и как их найти и исправить.

## Быстрая диагностика

```bash
asterisk -rx "pjsip show registrations"   # нужно Registered
asterisk -rx "pjsip show contacts"        # Avail / Unavail
asterisk -rx "core show channels"         # нет ли «зависших» звонков
systemctl is-active pioneer-agent
journalctl -u pioneer-agent --since "-15 min" --no-pager | grep -vE "GET /|POST /"
python3 scripts/sip_test.py               # регистрация в Zadarma без Asterisk
```

Подробный SIP-лог во время звонка: `asterisk -rvvv`, затем в консоли `pjsip set logger on`.

## Таблица симптомов

| Симптом | Причина | Решение |
|---|---|---|
| `Unregistered`, в логе уходит `REGISTER`, ответа нет, а `OPTIONS` получают `200 OK` | Домашний роутер (SIP ALG) или провайдер режут регистрацию | `ZADARMA_PROTO=tcp`; выключить SIP ALG; проверить через раздачу с телефона; надёжно — VPS |
| `sip_test.py`: `НЕТ ОТВЕТА` везде | Запросы не выходят из сети, либо Zadarma временно заблокировала IP после неудачных входов | Другая сеть; попросить поддержку разблокировать IP |
| `sip_test.py`: `401 -> 403` | Неверный пароль SIP | Обновить `ZADARMA_PASSWORD` и `password=` в `/etc/asterisk/pjsip.conf` |
| Asterisk шлёт запросы в Германию (`185.45.152.x`) | Собственный DNS-резолвер PJSIP выбирает дальний сервер | `ZADARMA_SERVER=sipal1.zadarma.com` |
| Звонок `failed`, длительность пустая | Контакт `Unavail` из-за непрошедших `OPTIONS`, Asterisk не начинает звонок | `qualify_frequency=0` (уже в шаблоне) |
| Панель: `AMI недоступен:` | WSL в режиме `mirrored` + `ufw`: соединения на `127.0.0.1` не проходят | `ufw disable` внутри WSL (скрипт пропускает файрвол в WSL) |
| `completed`, ~7 секунд, телефон не звонил; в BYE `Unallocated (unassigned) number` | Zadarma не пропускает звонок на мобильные (направление, страна аккаунта, CallerID) | Поддержка Zadarma: открыть направление Казахстан, CallerID |
| Звонок длится ровно 300 с, следующие уходят на автоответчик | Без регистрации до Asterisk не доходит `BYE`, звонок «висит», линия абонента занята | Вернуть регистрацию; `rtp_timeout=20` (уже в шаблоне); `channel request hangup all` |
| `403 Forbidden` на `/api/call` | Номер не в `ALLOWED_NUMBERS` или в стоп-листе | Добавить номер; очистить таблицу `dnc` |
| `python` не найден в Windows | Псевдоним Microsoft Store | Установить Python 3.12, выключить псевдонимы |
| `ZoneInfoNotFoundError` в Windows | Нет базы часовых поясов | `pip install tzdata` (уже в requirements) |

## Очистить стоп-лист

```bash
python3 -c "import sqlite3;c=sqlite3.connect('data/calls.db');c.execute('delete from dnc');c.commit()"
```

## Запуск на Windows через WSL

```powershell
wsl -d Ubuntu-24.04 -u root
```

`%USERPROFILE%\.wslconfig`:

```
[wsl2]
networkingMode=mirrored
```

Окно WSL не закрывайте во время работы, иначе Windows остановит Linux вместе с агентом.
