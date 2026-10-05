"""
Голосовой ИИ-агент отдела продаж (тестовый режим).
Телефония: Zadarma (SIP) -> Asterisk -> AudioSocket -> этот сервер -> OpenAI Realtime.

Запуск:  python app.py
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import db
import telephony

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("app")
db.init()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    server = await telephony.start_audiosocket_server()
    yield
    server.close()


app = FastAPI(title="Pioneer Voice Sales Agent", lifespan=lifespan)


def check_admin(token: str | None):
    if token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Неверный ADMIN_TOKEN")


def normalize(phone: str) -> str:
    p = "".join(ch for ch in phone if ch.isdigit())
    if p.startswith("8") and len(p) == 11:  # 8 777 ... -> 7 777 ...
        p = "7" + p[1:]
    return "+" + p


@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/health")
async def health():
    return {"ok": True, "test_mode": config.TEST_MODE, "model": config.REALTIME_MODEL}


class CallRequest(BaseModel):
    to: str
    lead_name: str = ""
    reason: str = ""


@app.post("/api/call")
async def make_call(req: CallRequest, x_admin_token: str | None = Header(None)):
    """Исходящий звонок клиенту через Asterisk + Zadarma."""
    check_admin(x_admin_token)
    to = normalize(req.to)
    if config.TEST_MODE and to not in [normalize(n) for n in config.ALLOWED_NUMBERS]:
        raise HTTPException(403, f"Тестовый режим: {to} нет в ALLOWED_NUMBERS")
    if db.is_dnc(to):
        raise HTTPException(403, f"{to} в стоп-листе (просил не звонить)")
    call_id = telephony.new_outbound(to, req.lead_name, req.reason)
    return {"call_sid": call_id, "to": to}


@app.get("/asterisk/inbound")
async def asterisk_inbound(uuid: str, phone: str = ""):
    """Asterisk сообщает о входящем звонке до подключения AudioSocket (из dialplan через CURL)."""
    phone = normalize(phone) if phone else ""
    telephony.pending[uuid] = {"direction": "inbound", "phone": phone}
    db.upsert_call(uuid, direction="inbound", phone=phone, status="in-progress")
    return "ok"


@app.get("/api/calls")
async def list_calls(x_admin_token: str | None = Header(None)):
    check_admin(x_admin_token)
    return db.query("SELECT * FROM calls ORDER BY started_at DESC LIMIT 200")


@app.get("/api/calls/{sid}")
async def call_detail(sid: str, x_admin_token: str | None = Header(None)):
    check_admin(x_admin_token)
    return {
        "call": (db.query("SELECT * FROM calls WHERE call_sid=?", (sid,)) or [None])[0],
        "transcript": db.query("SELECT role, text, ts FROM transcripts WHERE call_sid=? ORDER BY id", (sid,)),
    }


@app.get("/api/leads")
async def list_leads(x_admin_token: str | None = Header(None)):
    check_admin(x_admin_token)
    return {
        "leads": db.query("SELECT * FROM leads ORDER BY id DESC"),
        "callbacks": db.query("SELECT * FROM callbacks ORDER BY id DESC"),
        "dnc": db.query("SELECT * FROM dnc ORDER BY created_at DESC"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.HTTP_PORT)
