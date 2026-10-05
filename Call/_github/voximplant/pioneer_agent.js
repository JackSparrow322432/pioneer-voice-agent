/**
 * Pioneer — голосовой ИИ-продажник на Voximplant + OpenAI Realtime.
 *
 * Работает целиком в облаке Voximplant: никаких серверов, Asterisk и WSL.
 *   - Исходящий звонок: Routing -> правило -> Run, custom data:
 *       {"to":"+77000000000","name":"Аман","reason":"заявка на лагерь"}
 *   - Входящий звонок: если к приложению привязан номер, агент отвечает сам.
 *
 * Перед запуском: Settings -> Secrets -> добавьте OPENAI_API_KEY.
 */
require(Modules.OpenAI);
require(Modules.Net);

// ======================= НАСТРОЙКИ =======================
const MODEL = "gpt-realtime";
const VOICE = "marin";                 // варианты: marin, cedar, alloy, shimmer, coral
const AGENT_NAME = "Айгерим";
const CALLER_ID = "+77000000000";      // подтверждённый номер в Voximplant (Caller IDs) или купленный номер
const MAX_CALL_MS = 5 * 60 * 1000;     // максимум 5 минут на звонок
// Куда отправлять заявки (необязательно): URL, который принимает POST JSON.
// Например, Google Apps Script или ваш сервер. Пусто — заявки только в логах звонка.
const LEAD_WEBHOOK_URL = "";

// ======================= КАТАЛОГ =======================
// Цены null = агент не называет сумму и обещает расчёт менеджера. Впишите реальные.
const CATALOG = {
    resort: {
        name: "Горный курорт «Пионер» (Ski Park Pioneer)",
        address: "Алматы, Медеуский район, Алма-Тау, 27",
        phone: "+7 771 990 51 74",
        highlights: ["семейный курорт с 2015 года", "трассы около 3000 м, сертификация FIS, высота 2000+ м",
            "детский лагерь — более 1000 детей в год", "инклюзивная программа Pioneer Concept",
            "можно привозить свою еду"],
    },
    services: [
        {id: "ski_pass", category: "ski", name: "Ски-пасс", price_kzt: null, unit: "день"},
        {id: "ski_school", category: "ski", name: "Горнолыжная школа, дети с 3 лет", price_kzt: null, unit: "занятие"},
        {id: "rental", category: "ski", name: "Прокат снаряжения", price_kzt: null, unit: "день"},
        {id: "bungalow", category: "stay", name: "Бунгало у склона", price_kzt: null, unit: "сутки"},
        {id: "hotel_panorama", category: "stay", name: "Отель «Панорама», комфорт", price_kzt: null, unit: "сутки"},
        {id: "hotel_pioneer", category: "stay", name: "Отель «Пионер», бюджетный хостел", price_kzt: null, unit: "место/сутки"},
        {id: "cottage", category: "stay", name: "Коттедж с сауной", price_kzt: null, unit: "сутки"},
        {id: "kids_camp", category: "camp", name: "Детский лагерь 7–17 лет, смены на каникулах", price_kzt: null, unit: "смена"},
        {id: "adaptive_ski", category: "camp", name: "Адаптивное катание Pioneer Concept", price_kzt: null, unit: "занятие"},
        {id: "teambuilding", category: "corporate", name: "Тимбилдинг: проживание, питание, активности", price_kzt: null, unit: "по запросу"},
        {id: "hiking", category: "activity", name: "Походы в горы по выходным", price_kzt: null, unit: "человек"},
        {id: "horse_riding", category: "activity", name: "Конные прогулки", price_kzt: null, unit: "час"},
        {id: "transfer", category: "transport", name: "Трансфер, микроавтобус на 13 мест", price_kzt: null, unit: "поездка"},
    ],
    promotions: ["ДЕМО-АКЦИЯ (заменить): скидка 10% на зимний лагерь при бронировании до 1 ноября"],
};

// ======================= СКРИПТ ПРОДАЖ =======================
function buildInstructions(direction, name, reason) {
    const ctx = direction === "outbound"
        ? `Это ИСХОДЯЩИЙ звонок, ты звонишь клиенту сама.
Имя клиента: ${name || "неизвестно — спроси, как обращаться"}.
Повод звонка: ${reason || "клиент ранее интересовался курортом"}.
Первая фраза: поздоровайся, назови себя и курорт, скажи, что ты виртуальный ассистент, назови повод звонка одним предложением и спроси, удобно ли говорить.`
        : `Это ВХОДЯЩИЙ звонок. Первая фраза: поздоровайся, назови себя и курорт, скажи, что ты виртуальный ассистент, и спроси, чем помочь.`;

    return `Ты — ${AGENT_NAME}, голосовой менеджер отдела продаж горного курорта «Пионер» под Алматы.

${ctx}

# Язык
- По умолчанию говори по-русски.
- Если клиент говорит по-казахски или просит казахский — переходи на казахский.

# Стиль (это телефон)
- 1–2 коротких предложения за раз, потом вопрос. Тепло, живо, без канцелярита.
- Не зачитывай каталог: максимум 2 варианта. Числа и даты — словами.

# Цель
Довести до одного результата: заявка (create_lead), перезвон менеджера (schedule_callback) или вежливое завершение.

# Скрипт
1. Приветствие, «удобно ли говорить». Неудобно — спроси, когда перезвонить, schedule_callback, попрощайся, end_call.
2. Выяви потребность по одному вопросу: кто едет (дети и их возраст, семья, компания), что интересует (катание, школа, лагерь, отдых, тимбилдинг), когда, сколько человек.
3. Вызови get_services и предложи 1–2 подходящих варианта с пользой под ситуацию клиента.
4. Возражения: «дорого» — бюджетный отель или акция; «далеко» — рядом с Алматы, есть трансфер; «подумаю» — зафиксируем без обязательств, менеджер пришлёт расчёт; «ребёнок маленький» — школа с 3 лет.
5. Закрытие: подтверди имя, даты, количество людей, вызови create_lead, скажи, что менеджер свяжется с точным расчётом.
6. Попрощайся, затем вызови end_call.

# Правила
- НИКОГДА не придумывай цены, скидки, наличие мест и даты. Если цены нет — расчёт пришлёт менеджер.
- Спросят, робот ли ты, — честно скажи, что виртуальный ассистент.
- Просят не звонить — извинись, mark_do_not_call, попрощайся, end_call.
- Не дави, максимум одна повторная попытка. Номер телефона не спрашивай — он известен.`;
}

// ======================= ИНСТРУМЕНТЫ =======================
const TOOLS = [
    {type: "function", name: "get_services", description: "Услуги курорта, цены (null — цену называет менеджер) и акции.",
        parameters: {type: "object", properties: {category: {type: "string",
            enum: ["ski", "stay", "camp", "corporate", "activity", "transport", "all"]}}, required: ["category"]}},
    {type: "function", name: "create_lead", description: "Сохранить заявку после подтверждения данных клиентом.",
        parameters: {type: "object", properties: {
            name: {type: "string"}, service_ids: {type: "array", items: {type: "string"}},
            date_from: {type: "string"}, date_to: {type: "string"}, adults: {type: "integer"},
            children_ages: {type: "string"}, language: {type: "string", enum: ["ru", "kk"]},
            interest: {type: "string", enum: ["hot", "warm", "cold"]}, notes: {type: "string"}},
            required: ["name", "interest"]}},
    {type: "function", name: "schedule_callback", description: "Записать, когда клиенту удобно, чтобы перезвонили.",
        parameters: {type: "object", properties: {when_text: {type: "string"}, reason: {type: "string"}}, required: ["when_text"]}},
    {type: "function", name: "mark_do_not_call", description: "Клиент просит больше не звонить.",
        parameters: {type: "object", properties: {reason: {type: "string"}}}},
    {type: "function", name: "end_call", description: "Положить трубку. Вызывай ПОСЛЕ прощания.",
        parameters: {type: "object", properties: {outcome: {type: "string",
            enum: ["lead", "callback", "not_interested", "do_not_call", "other"]}}, required: ["outcome"]}},
];

function sendToWebhook(kind, data) {
    Logger.write(`===${kind.toUpperCase()}=== ${JSON.stringify(data)}`);
    if (!LEAD_WEBHOOK_URL) return;
    Net.httpRequestAsync(LEAD_WEBHOOK_URL, {
        method: "POST",
        headers: ["Content-Type: application/json"],
        postData: JSON.stringify(Object.assign({kind: kind}, data)),
    }).catch((e) => Logger.write(`===WEBHOOK_ERROR=== ${e}`));
}

// ======================= РАЗГОВОР =======================
async function runAgent(call, direction, info) {
    let client;
    let ending = false;
    const phone = info.to || call.callerid();
    const base = {phone: phone, direction: direction, name: info.name || ""};

    const hangupTimer = setTimeout(() => call.hangup(), MAX_CALL_MS);
    const finish = () => {
        clearTimeout(hangupTimer);
        if (client) client.close();
        VoxEngine.terminate();
    };
    call.addEventListener(CallEvents.Disconnected, finish);

    const hangupAfterSpeech = () => {
        // даём договорить прощание
        setTimeout(() => call.hangup(), 6000);
    };

    const runTool = (name, args) => {
        switch (name) {
            case "get_services": {
                const cat = args.category || "all";
                return {resort: CATALOG.resort, promotions: CATALOG.promotions,
                    services: CATALOG.services.filter((s) => cat === "all" || s.category === cat)};
            }
            case "create_lead":
                sendToWebhook("lead", Object.assign({}, base, args));
                return {ok: true, say: "Заявка сохранена, менеджер свяжется с точным расчётом."};
            case "schedule_callback":
                sendToWebhook("callback", Object.assign({}, base, args));
                return {ok: true};
            case "mark_do_not_call":
                sendToWebhook("do_not_call", Object.assign({}, base, args));
                return {ok: true};
            case "end_call":
                sendToWebhook("call_end", Object.assign({}, base, args));
                return {ok: true, note: "Звонок завершается. Больше ничего не говори."};
            default:
                return {ok: false, error: "unknown tool " + name};
        }
    };

    try {
        client = await OpenAI.createRealtimeAPIClient({
            apiKey: VoxEngine.getSecretValue("OPENAI_API_KEY"),
            model: MODEL,
            onWebSocketClose: (event) => {
                Logger.write("===OpenAI.WebSocket.Close=== " + JSON.stringify(event || {}));
                call.hangup();
            },
        });

        client.addEventListener(OpenAI.RealtimeAPIEvents.SessionCreated, () => {
            client.sessionUpdate({
                session: {
                    type: "realtime",
                    model: MODEL,
                    instructions: buildInstructions(direction, info.name, info.reason),
                    output_modalities: ["audio"],
                    audio: {
                        input: {
                            transcription: {model: "gpt-4o-mini-transcribe"},
                            turn_detection: {type: "server_vad", silence_duration_ms: 600, interrupt_response: true},
                        },
                        output: {voice: VOICE},
                    },
                    tools: TOOLS,
                    tool_choice: "auto",
                },
            });
        });

        client.addEventListener(OpenAI.RealtimeAPIEvents.SessionUpdated, () => {
            VoxEngine.sendMediaBetween(call, client);
            client.conversationItemCreate({
                item: {type: "message", role: "user", content: [{type: "input_text",
                    text: direction === "outbound"
                        ? "[Система: клиент взял трубку. Начни разговор по скрипту.]"
                        : "[Система: входящий звонок. Поприветствуй клиента.]"}]},
            });
            client.responseCreate({});
        });

        // Клиент перебил — останавливаем голос агента
        client.addEventListener(OpenAI.RealtimeAPIEvents.InputAudioBufferSpeechStarted, () => {
            if (!ending) client.clearMediaBuffer();
        });

        client.addEventListener(OpenAI.RealtimeAPIEvents.ResponseFunctionCallArgumentsDone, (event) => {
            const p = (event && event.data && (event.data.payload || event.data)) || {};
            const name = p.name || p.tool_name;
            const callId = p.call_id || p.callId;
            let args = {};
            try { args = typeof p.arguments === "string" ? JSON.parse(p.arguments) : (p.arguments || {}); } catch (e) { args = {}; }
            if (!name || !callId) return;

            const result = runTool(name, args);
            client.conversationItemCreate({item: {type: "function_call_output", call_id: callId,
                output: JSON.stringify(result)}});
            if (name === "end_call") {
                ending = true;
                hangupAfterSpeech();
            } else {
                client.responseCreate({});
            }
        });

        // Расшифровка разговора — в логи звонка (Call history -> Logs)
        client.addEventListener(OpenAI.RealtimeAPIEvents.ResponseOutputAudioTranscriptDone, (event) => {
            const p = (event && event.data && (event.data.payload || event.data)) || {};
            Logger.write("АГЕНТ: " + (p.transcript || ""));
        });
        client.addEventListener(OpenAI.RealtimeAPIEvents.ConversationItemInputAudioTranscriptionCompleted, (event) => {
            const p = (event && event.data && (event.data.payload || event.data)) || {};
            Logger.write("КЛИЕНТ: " + (p.transcript || ""));
        });
        [OpenAI.RealtimeAPIEvents.WebSocketError, OpenAI.RealtimeAPIEvents.Unknown].forEach((ev) => {
            client.addEventListener(ev, (event) => Logger.write("===" + event.name + "=== " + JSON.stringify(event.data || {})));
        });
    } catch (error) {
        Logger.write("===ERROR=== " + error);
        call.hangup();
    }
}

// ======================= ИСХОДЯЩИЙ =======================
VoxEngine.addEventListener(AppEvents.Started, () => {
    const raw = VoxEngine.customData();
    if (!raw) return; // входящий звонок — обрабатывается ниже
    let info = {};
    try { info = JSON.parse(raw); } catch (e) { Logger.write("Неверный custom data: " + raw); VoxEngine.terminate(); return; }
    if (!info.to) { Logger.write("В custom data нет поля to"); VoxEngine.terminate(); return; }

    const call = VoxEngine.callPSTN(info.to, info.callerId || CALLER_ID);
    call.addEventListener(CallEvents.Failed, (e) => {
        Logger.write("===CALL_FAILED=== " + e.code + " " + e.reason);
        VoxEngine.terminate();
    });
    call.addEventListener(CallEvents.Connected, () => runAgent(call, "outbound", info));
});

// ======================= ВХОДЯЩИЙ =======================
VoxEngine.addEventListener(AppEvents.CallAlerting, (e) => {
    e.call.answer();
    e.call.addEventListener(CallEvents.Connected, () => runAgent(e.call, "inbound", {}));
});
