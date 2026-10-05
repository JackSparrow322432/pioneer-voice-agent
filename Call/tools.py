"""Инструменты (function calling), которые агент вызывает во время разговора."""
import json

import config
import db


def _catalog() -> dict:
    with open(config.CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


# Описания в формате OpenAI Realtime (session.tools)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "get_services",
        "description": "Список услуг курорта с ценами (price_kzt=null — цены нет, расчёт делает менеджер) и активные акции.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["ski", "stay", "camp", "corporate", "activity", "transport", "all"],
                             "description": "Категория; all — всё."}
            },
            "required": ["category"],
        },
    },
    {
        "type": "function",
        "name": "check_availability",
        "description": "Проверить наличие по услуге на даты (ДЕМО: окончательно подтверждает менеджер).",
        "parameters": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string"},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "guests": {"type": "integer"},
            },
            "required": ["service_id", "date_from"],
        },
    },
    {
        "type": "function",
        "name": "create_lead",
        "description": "Сохранить заявку клиента для менеджера. Вызывать после подтверждения данных клиентом.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "service_ids": {"type": "array", "items": {"type": "string"}},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "adults": {"type": "integer"},
                "children_ages": {"type": "string", "description": "Напр. '5, 9'"},
                "language": {"type": "string", "enum": ["ru", "kk"]},
                "interest": {"type": "string", "enum": ["hot", "warm", "cold"]},
                "notes": {"type": "string", "description": "Пожелания, возражения, бюджет"},
            },
            "required": ["name", "interest"],
        },
    },
    {
        "type": "function",
        "name": "schedule_callback",
        "description": "Записать, когда клиенту удобно, чтобы перезвонили.",
        "parameters": {
            "type": "object",
            "properties": {
                "when_text": {"type": "string", "description": "Напр. 'завтра после 18:00'"},
                "reason": {"type": "string"},
            },
            "required": ["when_text"],
        },
    },
    {
        "type": "function",
        "name": "mark_do_not_call",
        "description": "Клиент просит больше не звонить.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}},
    },
    {
        "type": "function",
        "name": "end_call",
        "description": "Завершить звонок. Вызывай ПОСЛЕ прощания.",
        "parameters": {
            "type": "object",
            "properties": {
                "outcome": {"type": "string",
                            "enum": ["lead", "callback", "not_interested", "do_not_call", "wrong_number", "other"]}
            },
            "required": ["outcome"],
        },
    },
]


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    """ctx: {call_sid, phone}. Возвращает dict, который отдаём модели."""
    call_sid, phone = ctx.get("call_sid", ""), ctx.get("phone", "")

    if name == "get_services":
        cat = _catalog()
        category = args.get("category", "all")
        services = [s for s in cat["services"] if category in ("all", None) or s["category"] == category]
        promos = [p["text"] for p in cat.get("promotions", []) if p.get("active")]
        return {"resort": cat["resort"], "services": services, "promotions": promos}

    if name == "check_availability":
        cat = _catalog()
        ids = {s["id"] for s in cat["services"]}
        if args.get("service_id") not in ids:
            return {"ok": False, "error": f"Неизвестная услуга. Доступные id: {sorted(ids)}"}
        if args.get("date_from") in cat.get("blocked_dates", []):
            return {"available": False, "note": "На эти даты мест нет, предложи соседние даты."}
        return {"available": "likely",
                "note": "Демо-режим: скажи, что места, скорее всего, есть, но окончательно подтвердит менеджер."}

    if name == "create_lead":
        lead_id = db.execute(
            """INSERT INTO leads (call_sid, phone, name, service_ids, date_from, date_to, adults,
               children_ages, language, interest, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (call_sid, phone, args.get("name"), ",".join(args.get("service_ids") or []),
             args.get("date_from"), args.get("date_to"), args.get("adults"), args.get("children_ages"),
             args.get("language"), args.get("interest"), args.get("notes"), db.now()),
        )
        return {"ok": True, "lead_id": lead_id,
                "say": "Заявка сохранена. Менеджер свяжется с точным расчётом в рабочее время."}

    if name == "schedule_callback":
        db.execute("INSERT INTO callbacks (call_sid, phone, when_text, reason, created_at) VALUES (?,?,?,?,?)",
                   (call_sid, phone, args.get("when_text"), args.get("reason"), db.now()))
        return {"ok": True}

    if name == "mark_do_not_call":
        db.execute("INSERT OR REPLACE INTO dnc (phone, reason, created_at) VALUES (?,?,?)",
                   (phone, args.get("reason"), db.now()))
        return {"ok": True, "say": "Номер добавлен в стоп-лист."}

    if name == "end_call":
        db.upsert_call(call_sid, outcome=args.get("outcome"))
        return {"ok": True, "note": "Звонок будет завершён после твоей последней фразы. Больше ничего не говори."}

    return {"ok": False, "error": f"Неизвестный инструмент {name}"}


def chat_tool_schemas() -> list[dict]:
    """Те же инструменты в формате Chat Completions — для текстового симулятора."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in TOOL_SCHEMAS]
