# Pioneer на Voximplant: без сервера, Asterisk и WSL

Весь агент — один файл `pioneer_agent.js`. Он работает в облаке Voximplant:
звонок, голос OpenAI Realtime, скрипт продаж, каталог и заявки.

## Настройка (один раз)

1. **Баланс.** Пополните счёт на $5–10 (Top up balance). С $0.10 звонок не пройдёт.
2. **Ключ OpenAI.** Settings → **Secrets** → Add → имя `OPENAI_API_KEY`, значение — ваш **новый** ключ.
3. **Номер, с которого звоним (Caller ID).** Settings → **Caller IDs** → добавьте свой мобильный `+77000000000`
   и подтвердите кодом из звонка. Или купите номер в разделе Numbers.
   Если номер другой, поменяйте `CALLER_ID` в начале скрипта.
4. **Приложение.** Applications → **Create** → имя `pioneer`.
5. **Сценарий.** В приложении: Scenarios → **Create** → имя `pioneer_agent` → вставьте весь код из `pioneer_agent.js` → **Save**.
6. **Правило.** Routing → **Create rule** → имя `call`, pattern `.*`, сценарий `pioneer_agent` → **Save**.

## Звонок

Routing → правило `call` → **Run** → в поле Custom data:

```json
{"to":"+77000000000","name":"Аман","reason":"заявка на лагерь"}
```

→ **Run**. Телефон зазвонит, агент начнёт разговор.
Ограничение Voximplant: custom data до 200 байт, повод звонка пишите коротко.

## Где смотреть результат

**Call history** → звонок → **Logs**: реплики `АГЕНТ:` и `КЛИЕНТ:`, заявки `===LEAD===`,
перезвоны `===CALLBACK===`, стоп-лист `===DO_NOT_CALL===`, ошибки.

Чтобы заявки приходили в таблицу или CRM, укажите URL в `LEAD_WEBHOOK_URL`: туда уйдёт POST с JSON.

## Что править

В начале файла: `VOICE`, `AGENT_NAME`, `CALLER_ID`, `MAX_CALL_MS`, каталог `CATALOG` (впишите цены)
и скрипт в `buildInstructions`. После правки нажмите Save в сценарии.
