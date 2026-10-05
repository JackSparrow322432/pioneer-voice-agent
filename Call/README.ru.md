# Pioneer: голосовой ИИ-продажник (Zadarma + Asterisk)

> English: [README.md](README.md) · Разбор проблем: [docs/troubleshooting.md](docs/troubleshooting.md)

Агент сам звонит клиенту на телефон, говорит по-русски или по-казахски, выясняет потребность,
предлагает услуги курорта «Пионер», оформляет заявку или договаривается о перезвоне и кладёт трубку.
Входящие на ваш номер Zadarma он тоже принимает.

```
Телефон клиента ⇄ Zadarma (SIP) ⇄ Asterisk на VPS ⇄ AudioSocket ⇄ app.py ⇄ OpenAI Realtime
                                     ▲ AMI «позвони»           │
                                     └──── веб-панель ─────────┴─ SQLite: звонки, расшифровки, заявки
```

## Файлы

| Файл | Что делает |
|---|---|
| `app.py` | Веб-панель и API: кнопка «Позвонить», звонки, заявки |
| `telephony.py` | Связь с Asterisk: звук звонка (AudioSocket) и команда «позвонить» (AMI) |
| `agent.py` | Разговор с OpenAI Realtime: перебивание, инструменты, расшифровки |
| `prompt.py` | Скрипт продаж. **Правьте здесь** |
| `catalog.json` | Услуги и цены. **Впишите реальные цены** |
| `tools.py` | Действия агента: каталог, заявка, перезвон, стоп-лист, завершить звонок |
| `asterisk/` | Конфиги Asterisk: транк Zadarma, сценарии звонков, AMI |
| `setup_vps.sh` | Установка всего на сервер одной командой |
| `scripts/sip_test.py` | Проверка логина/пароля SIP и сети без Asterisk |
| `chat_sim.py` | Текстовая проверка скрипта без звонков (работает и на Windows) |

## Почему нужен VPS

Asterisk работает только на Linux, а Zadarma должна видеть сервер с белым IP.
Возьмите самый простой VPS: **Ubuntu 24.04, 1–2 ГБ RAM** (PS.kz, Hoster.kz, Hetzner и т. п.; около $5 в месяц).
Ваш Windows-компьютер нужен только для браузера и SSH.

## Шаг 1. Кабинет Zadarma

1. **Настройки → SIP-подключение** (или «АТС → Внутренние номера», если пользуетесь их АТС).
   Запишите **логин SIP** (вида `123456` или `123456-100`) и **пароль SIP**.
2. **CallerID**: в настройках этого SIP выберите ваш виртуальный номер. Без него звонки на казахстанские
   мобильные могут не проходить или приходить со скрытого номера.
3. **Входящие** (по желанию): «Виртуальные номера» → ваш номер → направить на этот SIP-логин.
4. Пополните баланс и проверьте тариф на мобильные Казахстана.
5. Если в Zadarma включено ограничение доступа по IP, добавьте IP вашего VPS.

## Шаг 2. Установка на VPS

С Windows (PowerShell):

```powershell
scp -r C:\Users\Admin\Desktop\зшщтуук root@IP_СЕРВЕРА:/opt/pioneer
ssh root@IP_СЕРВЕРА
```

На сервере:

```bash
cd /opt/pioneer
[ -f .env ] || cp .env.example .env
nano .env
bash setup_vps.sh
```

В `.env` должны быть заполнены `OPENAI_API_KEY`, `ZADARMA_LOGIN`, `ZADARMA_PASSWORD`, `OUTBOUND_CALLER_ID`,
`ZADARMA_SERVER` (по умолчанию `sipal1.zadarma.com`, Алматы), `ZADARMA_PROTO` (по умолчанию `tcp`),
`ADMIN_TOKEN` и `ALLOWED_NUMBERS`. Если `.env` скопирован с Windows, допишите в него недостающие строки из `.env.example`.
В nano сохранить: Ctrl+O, Enter; выйти: Ctrl+X.

Скрипт поставит Asterisk и Python, настроит транк Zadarma, запустит агента как службу и откроет порты.
В конце он покажет статус регистрации: должно быть **Registered**.

## Шаг 3. Звонок

Откройте `http://IP_СЕРВЕРА:5050`, введите `ADMIN_TOKEN`, свой номер (он должен быть в `ALLOWED_NUMBERS`),
имя и повод звонка и нажмите **«Позвонить»**.

Что смотреть, если что-то не так:

```bash
journalctl -u pioneer-agent -f            # разговор, инструменты, ошибки агента
asterisk -rvvv                            # консоль Asterisk (выход: exit)
asterisk -rx "pjsip show registrations"   # регистрация в Zadarma
```

## Частые проблемы

| Симптом | Причина |
|---|---|
| `Unregistered` / `Rejected` | Неверный логин или пароль SIP, либо IP VPS не разрешён в Zadarma |
| Статус звонка `congestion` / `failed` | Нет денег на балансе Zadarma, неверный формат номера, не задан CallerID |
| Трубку взяли, а там тишина | Неверный `OPENAI_API_KEY` (смотрите `journalctl`) или закрыты UDP-порты 10000–20000 |
| Клиента не слышно агенту | NAT: у VPS должен быть белый IP; проверьте `rtp_symmetric=yes` в `/etc/asterisk/pjsip.conf` |
| `AMI: неверный логин/пароль` | `AMI_SECRET` в `.env` не совпадает с `/etc/asterisk/manager.conf`: перезапустите `setup_vps.sh` |

После правки `prompt.py` или `catalog.json` перезапустите агента: `systemctl restart pioneer-agent`.

## Защита от лишних расходов (включена)

- `TEST_MODE=true`: звонки только на номера из `ALLOWED_NUMBERS`.
- `MAX_CALL_SECONDS=300`: звонок обрывается после 5 минут.
- `ADMIN_TOKEN` закрывает панель и API. AMI и AudioSocket доступны только внутри сервера.
- Стоп-лист: если клиент попросил не звонить, номер блокируется.

## Стоимость минуты (ориентир)

Zadarma по вашему тарифу плюс OpenAI `gpt-realtime` (примерно $0.1–0.3 за минуту разговора).
Для «боевой» версии без внешних AI-API меняется только `agent.py`: Whisper, локальная LLM и TTS.
Телефония, панель и скрипт остаются прежними.

## Текстовая проверка (на Windows, без звонков)

```powershell
.venv\Scripts\activate
python chat_sim.py
```
