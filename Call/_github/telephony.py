"""
Телефония через Asterisk:
  * AudioSocket — Asterisk присылает звук звонка по TCP (slin 16 бит, 8 кГц), мы отвечаем голосом агента.
  * AMI — даём Asterisk команду позвонить клиенту через транк Zadarma (Originate).

Протокол AudioSocket: [тип 1 байт][длина 2 байта big-endian][данные]
  0x00 — положить трубку, 0x01 — UUID звонка (16 байт), 0x03 — DTMF, 0x10 — аудио, 0xff — ошибка.
"""
import asyncio
import logging
import time
import uuid as uuidlib

try:
    import audioop  # Python <= 3.12
except ImportError:  # Python 3.13+: pip install audioop-lts
    import audioop_lts as audioop  # type: ignore

import config
import db
from agent import RealtimeCall

log = logging.getLogger("telephony")

KIND_HANGUP, KIND_UUID, KIND_DTMF, KIND_AUDIO, KIND_ERROR = 0x00, 0x01, 0x03, 0x10, 0xFF
FRAME_BYTES = 320  # 20 мс slin 8 кГц
FRAME_SEC = 0.02

# Контекст звонков, которые ждут подключения AudioSocket: uuid -> dict
pending: dict[str, dict] = {}


def frame(kind: int, payload: bytes = b"") -> bytes:
    return bytes([kind]) + len(payload).to_bytes(2, "big") + payload


class AsteriskCall(RealtimeCall):
    def __init__(self, reader, writer, call_id: str, ctx: dict):
        super().__init__(call_id, ctx.get("direction", "inbound"), ctx.get("phone", ""),
                         ctx.get("lead_name", ""), ctx.get("reason", ""))
        self.reader, self.writer = reader, writer
        self.out = bytearray()          # slin, ещё не отправленный в Asterisk
        self.item_played = 0            # байт текущей реплики, уже отправленных
        self.started = time.monotonic()

    # --- транспорт
    async def play(self, ulaw: bytes):
        self.out += audioop.ulaw2lin(ulaw, 2)

    async def stop_playback(self):
        self.out.clear()

    def on_new_item(self):
        self.item_played = 0

    def played_ms(self) -> int:
        return self.item_played // 16  # 16 байт = 1 мс

    def playback_pending(self) -> bool:
        return len(self.out) > 0

    async def hangup(self):
        if self.writer.is_closing():
            return
        try:
            self.writer.write(frame(KIND_HANGUP))
            await self.writer.drain()
        except (ConnectionError, RuntimeError):
            pass
        self.writer.close()

    # --- циклы
    async def pacer(self):
        """Отдаём звук в Asterisk ровно в реальном времени: 320 байт каждые 20 мс."""
        next_t = time.monotonic()
        while not self.writer.is_closing():
            if len(self.out) >= FRAME_BYTES or (self.out and self.hangup_requested):
                chunk = bytes(self.out[:FRAME_BYTES]).ljust(FRAME_BYTES, b"\x00")
                del self.out[:FRAME_BYTES]
                self.item_played += FRAME_BYTES
                try:
                    self.writer.write(frame(KIND_AUDIO, chunk))
                    await self.writer.drain()
                except (ConnectionError, RuntimeError):
                    break
            next_t += FRAME_SEC
            delay = next_t - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_t = time.monotonic()

    async def asterisk_loop(self):
        try:
            while True:
                head = await self.reader.readexactly(3)
                kind, length = head[0], int.from_bytes(head[1:3], "big")
                payload = await self.reader.readexactly(length) if length else b""
                if kind == KIND_AUDIO:
                    await self.send_caller_audio(audioop.lin2ulaw(payload, 2))
                elif kind == KIND_HANGUP:
                    log.info("[%s] клиент положил трубку", self.call_id[:8])
                    break
                elif kind == KIND_DTMF:
                    log.info("[%s] DTMF %s", self.call_id[:8], payload.decode(errors="ignore"))
                elif kind == KIND_ERROR:
                    log.warning("[%s] ошибка AudioSocket %s", self.call_id[:8], payload.hex())
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            log.info("[%s] Asterisk закрыл соединение", self.call_id[:8])

    async def run(self):
        db.upsert_call(self.call_id, direction=self.direction, phone=self.phone, status="in-progress",
                       **({"lead_name": self.lead_name} if self.lead_name else {}))
        tasks = []
        try:
            await self.connect()
            tasks = [asyncio.create_task(self.openai_loop()), asyncio.create_task(self.pacer())]
            await asyncio.wait_for(self.asterisk_loop(), timeout=config.MAX_CALL_SECONDS)
        except asyncio.TimeoutError:
            log.info("[%s] превышена длительность звонка", self.call_id[:8])
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] ошибка звонка: %s", self.call_id[:8], e)
        finally:
            await self.close_openai()
            await self.hangup()
            for t in tasks:
                t.cancel()
            db.upsert_call(self.call_id, status="completed", ended_at=db.now(),
                           duration=int(time.monotonic() - self.started))


async def handle_audiosocket(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        head = await asyncio.wait_for(reader.readexactly(3), timeout=5)
        if head[0] != KIND_UUID:
            writer.close()
            return
        raw = await reader.readexactly(int.from_bytes(head[1:3], "big"))
        call_id = str(uuidlib.UUID(bytes=raw))
    except Exception:  # noqa: BLE001
        writer.close()
        return
    ctx = pending.pop(call_id, None) or {"direction": "inbound"}
    log.info("Звонок подключён %s (%s, %s)", call_id, ctx.get("direction"), ctx.get("phone", "?"))
    await AsteriskCall(reader, writer, call_id, ctx).run()


async def start_audiosocket_server():
    server = await asyncio.start_server(handle_audiosocket, config.AUDIOSOCKET_HOST, config.AUDIOSOCKET_PORT)
    log.info("AudioSocket слушает %s:%s", config.AUDIOSOCKET_HOST, config.AUDIOSOCKET_PORT)
    return server


# ---------------------------------------------------------------- AMI

REASONS = {"0": "failed", "1": "hangup", "3": "no-answer", "4": "answered", "5": "busy", "8": "congestion"}


async def _ami_read_block(reader) -> dict:
    block = {}
    while True:
        line = (await reader.readline()).decode(errors="ignore").rstrip("\r\n")
        if not line:
            if block:
                return block
            continue
        if ": " in line:
            k, v = line.split(": ", 1)
            block[k] = v


async def originate(number_digits: str, call_id: str):
    """Позвонить клиенту. Выполняется в фоне, результат пишет в БД."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(config.AMI_HOST, config.AMI_PORT), 5)
    except Exception as e:  # noqa: BLE001
        db.upsert_call(call_id, status="failed", outcome=f"AMI недоступен: {e}")
        log.error("AMI недоступен: %s", e)
        return
    try:
        await reader.readline()  # приветствие Asterisk Call Manager
        writer.write((f"Action: Login\r\nUsername: {config.AMI_USER}\r\nSecret: {config.AMI_SECRET}\r\n"
                      f"Events: call\r\n\r\n").encode())
        await writer.drain()
        resp = await asyncio.wait_for(_ami_read_block(reader), 5)
        if resp.get("Response") != "Success":
            db.upsert_call(call_id, status="failed", outcome="AMI: неверный логин/пароль")
            log.error("AMI login: %s", resp)
            return
        channel = config.DIAL_TEMPLATE.format(number=number_digits)
        lines = [
            "Action: Originate", f"ActionID: {call_id}", f"Channel: {channel}",
            "Context: ai-outbound", "Exten: s", "Priority: 1",
            f"Timeout: {config.RING_TIMEOUT_SEC * 1000}", f"Variable: AI_UUID={call_id}", "Async: true",
        ]
        if config.OUTBOUND_CALLER_ID:
            lines.append(f"CallerID: {config.OUTBOUND_CALLER_ID}")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await writer.drain()
        db.upsert_call(call_id, status="ringing")
        log.info("Originate %s -> %s", call_id[:8], channel)
        deadline = time.monotonic() + config.RING_TIMEOUT_SEC + 20
        while time.monotonic() < deadline:
            ev = await asyncio.wait_for(_ami_read_block(reader), deadline - time.monotonic())
            if ev.get("Event") == "OriginateResponse" and ev.get("ActionID") == call_id:
                reason = REASONS.get(ev.get("Reason", ""), ev.get("Reason", ""))
                log.info("Originate %s: %s (%s)", call_id[:8], ev.get("Response"), reason)
                if ev.get("Response") != "Success":
                    db.upsert_call(call_id, status=reason or "failed", ended_at=db.now())
                break
            if ev.get("Response") == "Error" and ev.get("ActionID") == call_id:
                db.upsert_call(call_id, status="failed", outcome=ev.get("Message", "")[:200])
                log.error("Originate ошибка: %s", ev)
                break
    except asyncio.TimeoutError:
        log.warning("Originate %s: нет ответа от Asterisk", call_id[:8])
    finally:
        try:
            writer.write(b"Action: Logoff\r\n\r\n")
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def new_outbound(phone: str, lead_name: str, reason: str) -> str:
    call_id = str(uuidlib.uuid4())
    pending[call_id] = {"direction": "outbound", "phone": phone, "lead_name": lead_name, "reason": reason}
    db.upsert_call(call_id, direction="outbound", phone=phone, lead_name=lead_name, reason=reason, status="initiated")
    asyncio.create_task(originate(phone.lstrip("+"), call_id))
    return call_id
