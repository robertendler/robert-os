"""Der Dauerdienst, der Robert zuhoert.

Laeuft rund um die Uhr auf dem Server, haengt an Telegram und gibt jede
Nachricht an den zustaendigen Agenten weiter. Antwort in Sekunden.
"""

from __future__ import annotations

import signal
import sqlite3
import time
from typing import Any

from . import chat, db, telegram
from .config import AGENT_LABELS, Config

WARTEZEIT = 45          # So lange haelt Telegram die Verbindung offen.
FEHLER_PAUSE = 5        # Pause nach einem Fehler, in Sekunden.
MAX_PAUSE = 60


class Beenden(Exception):
    """Wird ausgeloest, wenn der Dienst gestoppt werden soll."""


def _signale_abfangen() -> None:
    def stoppen(signum, rahmen):  # noqa: ARG001
        raise Beenden()

    signal.signal(signal.SIGTERM, stoppen)
    signal.signal(signal.SIGINT, stoppen)


def _hilfetext() -> str:
    zeilen = [
        "Robert-OS ist da. Schreib mir einfach.",
        "",
        "Ich leite deine Nachricht an den zustaendigen Agenten weiter.",
        "Wenn du jemanden direkt willst, stell das voran:",
        "",
        "  @chef         Tagessteuerung, Prioritaeten, Nachhalten",
        "  @sales        Kunden, Angebote, Nachfassen, Umsatz",
        "  @performance  Schlaf, Bewegung, Energie, Konzentration",
        "  @check        Faktencheck und unbequeme Wahrheiten",
        "",
        "Beispiel:  @sales Was ist mit Meier?",
        "",
        "Befehle:",
        "  /status   Was das System gerade weiss",
        "  /hilfe    Diese Uebersicht",
    ]
    return "\n".join(zeilen)


def _statustext(conn: sqlite3.Connection) -> str:
    zeilen = ["Stand von Robert-OS:", ""]
    for agent, label in AGENT_LABELS.items():
        zustaende = db.get_states(conn, agent)
        offen = db.open_handoffs(conn, agent)
        ziele = db.open_goals(conn, agent)
        zeilen.append(
            f"{label}: {len(zustaende)} Notizen, {len(offen)} offene Uebergaben, "
            f"{len(ziele)} offene Ziele"
        )
    letzte = conn.execute(
        "SELECT agent, action, result, timestamp FROM execution_log "
        "ORDER BY id DESC LIMIT 3"
    ).fetchall()
    if letzte:
        zeilen.append("")
        zeilen.append("Zuletzt gelaufen:")
        for reihe in letzte:
            zeilen.append(
                f"  {reihe['timestamp'][:16]} {AGENT_LABELS.get(reihe['agent'], reihe['agent'])}"
                f" ({reihe['action']}, {reihe['result']})"
            )
    return "\n".join(zeilen)


def _behandle_nachricht(
    conn: sqlite3.Connection, config: Config, chat_id: str, text: str
) -> None:
    token = config.telegram_bot_token
    befehl = text.strip().lower().split()[0] if text.strip() else ""

    if befehl in {"/start", "/hilfe", "/help"}:
        telegram.send_message(token, chat_id, _hilfetext())
        return
    if befehl == "/status":
        telegram.send_message(token, chat_id, _statustext(conn))
        return

    telegram.send_chat_action(token, chat_id, "typing")
    lauf = chat.beantworte(conn, config, chat_id, text)

    if not lauf.ok:
        telegram.send_message(
            token, chat_id,
            "Da ist etwas schiefgegangen und ich will dir nichts vormachen:\n\n"
            f"{lauf.error}\n\n"
            "Deine Nachricht ist gespeichert, es ist nichts verloren.",
        )
        return
    if not lauf.telegram_text:
        telegram.send_message(
            token, chat_id,
            "Verstanden, notiert. Von mir aus gibt es dazu gerade nichts zu sagen.",
        )


def lauf(config: Config, einmal: bool = False) -> int:
    """Startet den Dauerdienst. Kehrt erst beim Beenden zurueck."""
    token, chat_id = config.require_telegram()
    conn = db.init_db(config.db_path)
    _signale_abfangen()

    stand = db.kv_get(conn, "telegram_offset")
    offset = int(stand) + 1 if stand else None
    pause = FEHLER_PAUSE

    print("Robert-OS Bot laeuft. Beenden mit Strg+C.", flush=True)
    try:
        while True:
            try:
                updates = telegram.get_updates(
                    token, offset=offset, warte_sekunden=WARTEZEIT
                )
                pause = FEHLER_PAUSE
            except Exception as fehler:  # Netz weg, Telegram gestoert, ...
                print(f"Telegram nicht erreichbar: {fehler}", flush=True)
                time.sleep(pause)
                pause = min(pause * 2, MAX_PAUSE)
                continue

            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                with db.transaction(conn):
                    db.kv_set(conn, "telegram_offset", str(offset - 1))

                nachricht: dict[str, Any] = (
                    update.get("message") or update.get("edited_message") or {}
                )
                text = (nachricht.get("text") or "").strip()
                absender = str((nachricht.get("chat") or {}).get("id", ""))
                # Nur der eigene Chat wird bedient.
                if not text or absender != str(chat_id):
                    continue

                print(f"Nachricht von Robert: {text[:60]}", flush=True)
                try:
                    _behandle_nachricht(conn, config, absender, text)
                except Exception as fehler:
                    print(f"Fehler beim Beantworten: {fehler}", flush=True)
                    try:
                        telegram.send_message(
                            token, absender,
                            f"Fehler beim Beantworten: {fehler}",
                        )
                    except Exception:
                        pass

            if einmal:
                return 0
    except Beenden:
        print("Bot beendet.", flush=True)
        return 0
    finally:
        conn.close()
