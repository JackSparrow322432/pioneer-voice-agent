"""
Ядро голосового агента: разговор с OpenAI Realtime, инструменты, расшифровки.
Не зависит от телефонии: транспорт (Asterisk AudioSocket) наследуется от RealtimeCall
и реализует play / stop_playback / played_ms / playback_pending / hangup.
Аудио на входе и выходе: G.711 µ-law 8 кГц.
"""
import asyncio
import base64
import json
import logging

import websockets

import config
import db
from prompt import build_instructions, greeting_trigger
from tools import TOOL_SCHEMAS, run_tool

log = logging.getLogger("agent")


class RealtimeCall:
    def __init__(self, call_id: str, direction: str, phone: str, lead_name: str = "", reason: str = ""):
        self.call_id = call_id
        self.direction = direction
        self.phone = phone
        self.lead_name = lead_name
        self.reason = reason
        self.oa = None
        self.current_item = None        # id реплики агента, которая сейчас звучит
        self.hangup_requested = False
        self.closed = False

    # ---------- транспорт (переопределяется) ----------
    async def play(self, ulaw: bytes): ...
    async def stop_playback(self): ...
    def played_ms(self) -> int: return 0
    def playback_pending(self) -> bool: return False
    async def hangup(self): ...

    # ---------- вход от телефонии ----------
    async def send_caller_audio(self, ulaw: bytes):
        if self.oa and not self.closed:
            try:
                await self.oa.send(json.dumps({"type": "input_audio_buffer.append",
                                               "audio": base64.b64encode(ulaw).decode()}))
            except websockets.ConnectionClosed:
                pass

    # ---------- OpenAI ----------
    async def connect(self):
        url = f"{config.REALTIME_URL}?model={config.REALTIME_MODEL}"
        self.oa = await websockets.connect(
            url, additional_headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"}, max_size=None)
        await self.oa.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": config.REALTIME_MODEL,
                "output_modalities": ["audio"],
                "instructions": build_instructions(self.direction, self.lead_name, self.reason),
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},
                        "transcription": {"model": config.TRANSCRIBE_MODEL},
                        "turn_detection": {"type": "server_vad", "silence_duration_ms": 600,
                                           "prefix_padding_ms": 300, "threshold": 0.5},
                    },
                    "output": {"format": {"type": "audio/pcmu"}, "voice": config.VOICE},
                },
                "tools": TOOL_SCHEMAS,
                "tool_choice": "auto",
            },
        }))
        # Агент говорит первым
        await self.oa.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": greeting_trigger(self.direction)}]},
        }))
        await self.oa.send(json.dumps({"type": "response.create"}))

    async def openai_loop(self):
        try:
            async for raw in self.oa:
                ev = json.loads(raw)
                t = ev.get("type")

                if t == "response.output_audio.delta":
                    item = ev.get("item_id")
                    if item and item != self.current_item:
                        self.current_item = item
                        self.on_new_item()
                    await self.play(base64.b64decode(ev["delta"]))

                elif t == "input_audio_buffer.speech_started":
                    await self.handle_interruption()

                elif t == "response.output_audio_transcript.done":
                    db.add_transcript(self.call_id, "agent", ev.get("transcript", ""))
                    log.info("[%s] АГЕНТ: %s", self.call_id[:8], ev.get("transcript", ""))

                elif t == "conversation.item.input_audio_transcription.completed":
                    db.add_transcript(self.call_id, "client", ev.get("transcript", ""))
                    log.info("[%s] КЛИЕНТ: %s", self.call_id[:8], ev.get("transcript", ""))

                elif t == "response.function_call_arguments.done":
                    await self.handle_tool(ev["name"], ev.get("arguments") or "{}", ev["call_id"])

                elif t == "error":
                    log.error("[%s] OpenAI error: %s", self.call_id[:8], ev.get("error"))
        except websockets.ConnectionClosed as e:
            log.info("[%s] OpenAI закрыл соединение: %s", self.call_id[:8], e)

    def on_new_item(self):
        """Началась новая реплика агента (транспорт сбрасывает счётчик проигранного)."""

    async def handle_interruption(self):
        """Клиент заговорил: обрезаем реплику агента на том месте, где он остановился."""
        if self.hangup_requested or not self.playback_pending() or not self.current_item:
            return
        await self.oa.send(json.dumps({"type": "conversation.item.truncate", "item_id": self.current_item,
                                       "content_index": 0, "audio_end_ms": self.played_ms()}))
        await self.stop_playback()
        log.info("[%s] перебивание на %d мс", self.call_id[:8], self.played_ms())

    async def handle_tool(self, name: str, arguments: str, call_id: str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
        log.info("[%s] ИНСТРУМЕНТ %s %s", self.call_id[:8], name, args)
        result = await asyncio.to_thread(run_tool, name, args, {"call_sid": self.call_id, "phone": self.phone})
        db.add_transcript(self.call_id, "tool", f"{name}({json.dumps(args, ensure_ascii=False)})")
        await self.oa.send(json.dumps({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id,
                     "output": json.dumps(result, ensure_ascii=False)},
        }))
        if name == "end_call":
            self.hangup_requested = True
            asyncio.create_task(self.hangup_after_playback())
        else:
            await self.oa.send(json.dumps({"type": "response.create"}))

    async def hangup_after_playback(self, timeout: float = 15.0):
        waited = 0.0
        await asyncio.sleep(0.3)
        while self.playback_pending() and waited < timeout and not self.closed:
            await asyncio.sleep(0.1)
            waited += 0.1
        await asyncio.sleep(0.5)
        log.info("[%s] кладу трубку", self.call_id[:8])
        await self.hangup()

    async def close_openai(self):
        self.closed = True
        if self.oa:
            try:
                await self.oa.close()
            except Exception:  # noqa: BLE001
                pass
