"""Настройки из .env"""
import os
from dotenv import load_dotenv

load_dotenv(override=True)  # .env важнее системных переменных Windows


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip().replace(" ", "") for x in raw.split(",") if x.strip()]


# --- OpenAI ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
REALTIME_URL = os.getenv("REALTIME_URL", "wss://api.openai.com/v1/realtime")
VOICE = os.getenv("VOICE", "marin")
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
SIM_MODEL = os.getenv("SIM_MODEL", "gpt-4o-mini")

# --- Asterisk ---
# AMI (управление Asterisk: исходящие звонки)
AMI_HOST = os.getenv("AMI_HOST", "127.0.0.1")
AMI_PORT = int(os.getenv("AMI_PORT", "5038"))
AMI_USER = os.getenv("AMI_USER", "aiagent")
AMI_SECRET = os.getenv("AMI_SECRET", "")
# Куда Asterisk шлёт звук звонка (AudioSocket)
AUDIOSOCKET_HOST = os.getenv("AUDIOSOCKET_HOST", "127.0.0.1")
AUDIOSOCKET_PORT = int(os.getenv("AUDIOSOCKET_PORT", "9092"))
# Как набирать номер через транк Zadarma. {number} = цифры без "+", напр. 77771234567
DIAL_TEMPLATE = os.getenv("DIAL_TEMPLATE", "PJSIP/{number}@zadarma")
OUTBOUND_CALLER_ID = os.getenv("OUTBOUND_CALLER_ID", "")
RING_TIMEOUT_SEC = int(os.getenv("RING_TIMEOUT_SEC", "30"))

# --- Панель ---
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
HTTP_PORT = int(os.getenv("HTTP_PORT", "5050"))

# Тестовый режим: звонить можно ТОЛЬКО на номера из ALLOWED_NUMBERS
TEST_MODE = os.getenv("TEST_MODE", "true").lower() in ("1", "true", "yes")
ALLOWED_NUMBERS = _list("ALLOWED_NUMBERS")

# Максимальная длительность звонка, секунд (защита бюджета)
MAX_CALL_SECONDS = int(os.getenv("MAX_CALL_SECONDS", "300"))

AGENT_NAME = os.getenv("AGENT_NAME", "Айгерим")
COMPANY_NAME = os.getenv("COMPANY_NAME", "горный курорт «Пионер»")

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "calls.db"))
CATALOG_PATH = os.getenv("CATALOG_PATH", os.path.join(os.path.dirname(__file__), "catalog.json"))
