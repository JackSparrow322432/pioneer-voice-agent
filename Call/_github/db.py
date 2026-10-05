"""SQLite: звонки, расшифровки, лиды, перезвоны, стоп-лист."""
import os
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_sid TEXT PRIMARY KEY,
    direction TEXT, phone TEXT, lead_name TEXT, reason TEXT,
    status TEXT, outcome TEXT, duration INTEGER,
    started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT, role TEXT, text TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT, phone TEXT, name TEXT, service_ids TEXT,
    date_from TEXT, date_to TEXT, adults INTEGER, children_ages TEXT,
    language TEXT, interest TEXT, notes TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS callbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_sid TEXT, phone TEXT, when_text TEXT, reason TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS dnc (
    phone TEXT PRIMARY KEY, reason TEXT, created_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def execute(sql: str, params: tuple = ()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def query(sql: str, params: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def upsert_call(call_sid: str, **fields):
    existing = query("SELECT call_sid FROM calls WHERE call_sid=?", (call_sid,))
    if not existing:
        execute("INSERT INTO calls (call_sid, started_at) VALUES (?, ?)", (call_sid, now()))
    if fields:
        cols = ", ".join(f"{k}=?" for k in fields)
        execute(f"UPDATE calls SET {cols} WHERE call_sid=?", (*fields.values(), call_sid))


def add_transcript(call_sid: str, role: str, text: str):
    if text and text.strip():
        execute("INSERT INTO transcripts (call_sid, role, text, ts) VALUES (?,?,?,?)",
                (call_sid, role, text.strip(), now()))


def is_dnc(phone: str) -> bool:
    return bool(query("SELECT 1 FROM dnc WHERE phone=?", (phone,)))
