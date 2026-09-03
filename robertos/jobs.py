"""Die geplanten Laeufe ("Jobs"), die der Server automatisch startet.

Ein Job ist eine feste Reihenfolge von Agenten. Die Reihenfolge ist
wichtig: Wer zuerst laeuft, kann dem Naechsten eine Uebergabe hinterlassen,
die dieser im selben Lauf schon sieht.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from . import agents as agents_mod
from . import db, telegram
from .config import Config

# Name des Jobs -> (Anlass fuer das Protokoll, Reihenfolge der Agenten)
JOBS: dict[str, tuple[str, list[str]]] = {
    "morgen": ("Morgensteuerung", ["performance_main", "robert_os_main"]),
    "accountability": ("Accountability Watch", ["robert_os_main"]),
    "abend": ("Abend-Sync", ["sales_main", "performance_main", "robert_os_main"]),
    "woche": ("Wochenreview", ["reality_check_main", "sales_main",
                               "performance_main", "robert_os_main"]),
    "orchestrierung": ("Orchestration Watch", ["reality_check_main", "robert_os_main"]),
}

JOB_DESCRIPTIONS = {
    "morgen": "Taeglich 07:20 - Tag planen, drei Prioritaeten setzen",
    "accountability": "Taeglich 11:30 und 16:30 - nachhaken, was vom Plan fehlt",
    "abend": "Taeglich 21:00 - Tag abschliessen, Offenes auf morgen ziehen",
    "woche": "Sonntags 19:00 - Woche auswerten, Faktencheck",
    "orchestrierung": "Optional stuendlich - offene Uebergaben abarbeiten",
}


def run_job(
    conn: sqlite3.Connection,
    config: Config,
    job: str,
    ask: Callable | None = None,
    notify: Callable | None = None,
) -> list[agents_mod.AgentRun]:
    if job not in JOBS:
        raise ValueError(
            f"Unbekannter Job: {job}. Moeglich sind: {', '.join(sorted(JOBS))}"
        )
    trigger, agent_list = JOBS[job]
    runs = []
    for agent in agent_list:
        runs.append(
            agents_mod.run_agent(conn, config, agent, trigger, ask=ask, notify=notify)
        )
    return runs


def poll_telegram(conn: sqlite3.Connection, config: Config) -> int:
    """Holt Nachrichten ab, die Robert dem Bot geschickt hat.

    Diese landen im Posteingang und werden vom naechsten Agentenlauf
    gelesen. So kann Robert dem System einfach per Telegram etwas sagen.
    """
    token, chat_id = config.require_telegram()
    last = db.kv_get(conn, "telegram_offset")
    offset = int(last) + 1 if last else None
    updates = telegram.get_updates(token, offset=offset)

    stored = 0
    highest = int(last) if last else 0
    for update in updates:
        highest = max(highest, int(update.get("update_id", 0)))
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        text = (message.get("text") or "").strip()
        sender_chat = str((message.get("chat") or {}).get("id", ""))
        # Nur Nachrichten aus dem eigenen Chat werden angenommen.
        if not text or sender_chat != str(chat_id):
            continue
        with db.transaction(conn):
            db.add_inbox(conn, "telegram", text)
        stored += 1

    if highest:
        with db.transaction(conn):
            db.kv_set(conn, "telegram_offset", str(highest))
    return stored
