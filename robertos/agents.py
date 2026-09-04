"""Der Ablauf eines Agentenlaufs.

Immer die gleiche Reihenfolge:
1. Daten aus der Datenbank lesen
2. Die KI mit diesem Stand befragen
3. Das Ergebnis in EINER Transaktion speichern
4. Erst danach die Telegram-Nachricht verschicken

Punkt 3 vor Punkt 4 ist Absicht: Es wird nie eine Erfolgsmeldung
verschickt, deren Aenderung nicht wirklich in der Datenbank steht.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import db, llm, telegram
from .config import AGENT_LABELS, AGENTS, PROJECT_ROOT, Config

PROMPT_DIR = PROJECT_ROOT / "prompts"
# Persoenliche Fassungen liegen hier. Der Ordner ist von der
# Versionsverwaltung ausgeschlossen und verlaesst den Server nie.
LOCAL_PROMPT_DIR = PROMPT_DIR / "local"
SHARED_NAME = "_gemeinsame_regeln"

STATUS_VALUES = ["open", "active", "blocked", "done"]

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "telegram_message": {"type": "string"},
        "summary": {"type": "string"},
        "checkin_note": {"type": "string"},
        "state_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        "handoffs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_agent": {"type": "string", "enum": list(AGENTS)},
                    "thread_key": {"type": "string"},
                    "type": {"type": "string"},
                    "facts": {"type": "string"},
                    "decision": {"type": "string"},
                    "next_step": {"type": "string"},
                },
                "required": [
                    "target_agent", "thread_key", "type",
                    "facts", "decision", "next_step",
                ],
                "additionalProperties": False,
            },
        },
        "processed_handoff_ids": {"type": "array", "items": {"type": "integer"}},
        "goal_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": STATUS_VALUES},
                    "due": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["title", "status", "due", "detail"],
                "additionalProperties": False,
            },
        },
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "number"},
                    "note": {"type": "string"},
                },
                "required": ["metric", "value", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "telegram_message", "summary", "checkin_note", "state_updates",
        "handoffs", "processed_handoff_ids", "goal_updates", "metrics",
    ],
    "additionalProperties": False,
}


@dataclass
class AgentRun:
    agent: str
    trigger: str
    ok: bool
    summary: str = ""
    telegram_text: str = ""
    telegram_sent: bool = False
    error: str = ""
    cost_note: str = ""
    applied: dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        label = AGENT_LABELS.get(self.agent, self.agent)
        if not self.ok:
            return f"[FEHLER] {label} ({self.trigger}): {self.error}"
        changes = ", ".join(f"{k}: {v}" for k, v in self.applied.items() if v)
        parts = [f"[OK] {label} ({self.trigger})"]
        if self.summary:
            parts.append(self.summary)
        if changes:
            parts.append(f"gespeichert -> {changes}")
        parts.append("Telegram gesendet" if self.telegram_sent else "keine Nachricht noetig")
        if self.cost_note:
            parts.append(self.cost_note)
        return " | ".join(parts)


def local_date(config: Config) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d")
    except Exception:  # pragma: no cover - falls Zeitzonendaten fehlen
        return datetime.now().strftime("%Y-%m-%d")


def local_now(config: Config) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # pragma: no cover
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def prompt_file(name: str) -> Path | None:
    """Findet den Rollentext. Eine persoenliche Fassung gewinnt.

    Liegt in prompts/local/ eine Datei gleichen Namens, wird sie benutzt.
    Sonst die mitgelieferte aus prompts/.
    """
    local = LOCAL_PROMPT_DIR / f"{name}.md"
    if local.exists():
        return local
    standard = PROMPT_DIR / f"{name}.md"
    return standard if standard.exists() else None


def load_system_prompt(agent: str) -> str:
    """Setzt den Rollentext zusammen: gemeinsame Regeln plus Rolle des Agenten."""
    agent_file = prompt_file(agent)
    if agent_file is None:
        raise FileNotFoundError(
            f"Rollentext fehlt: weder prompts/local/{agent}.md noch prompts/{agent}.md"
        )
    shared_file = prompt_file(SHARED_NAME)
    shared = shared_file.read_text(encoding="utf-8") if shared_file else ""
    return f"{shared}\n\n---\n\n{agent_file.read_text(encoding='utf-8')}"


def _rows_to_text(rows: list[sqlite3.Row], fields: tuple[str, ...]) -> str:
    if not rows:
        return "  (nichts vorhanden)"
    lines = []
    for row in rows:
        bits = []
        for name in fields:
            value = row[name]
            if value in (None, ""):
                continue
            bits.append(f"{name}={value}")
        lines.append("  - " + ", ".join(bits))
    return "\n".join(lines)


def build_context(
    conn: sqlite3.Connection, config: Config, agent: str, trigger: str
) -> tuple[str, list[int], list[int]]:
    """Baut den Text, den die KI zu sehen bekommt.

    Gibt zusaetzlich zurueck, welche Uebergaben und Posteingangs-Eintraege
    gezeigt wurden. Nur diese darf der Agent spaeter abhaken.
    """
    states = db.get_states(conn, agent)
    handoffs = db.open_handoffs(conn, agent)
    goals = db.open_goals(conn, agent)
    all_goals = db.open_goals(conn)
    metrics = db.recent_metrics(conn, agent, limit=15)
    log = db.recent_log(conn, agent, limit=10)
    inbox = db.unread_inbox(conn)

    handoff_ids = [int(row["id"]) for row in handoffs]
    inbox_ids = [int(row["id"]) for row in inbox]

    state_text = (
        "\n".join(f"  - {k}: {v}" for k, v in states.items())
        if states else "  (noch keine Zustaende gespeichert)"
    )
    inbox_text = (
        "\n".join(f"  - [{row['created_at']}] {row['text']}" for row in inbox)
        if inbox else "  (keine neuen Nachrichten von Robert)"
    )

    return (
        f"""AKTUELLER ZEITPUNKT: {local_now(config)} ({config.timezone})
ANLASS DIESES LAUFS: {trigger}
DEIN NAME: {AGENT_LABELS.get(agent, agent)}

== DEINE GESPEICHERTEN ZUSTAENDE ==
{state_text}

== OFFENE UEBERGABEN AN DICH ==
{_rows_to_text(handoffs, ("id", "source_agent", "thread_key", "type", "facts", "decision", "next_step", "created_at"))}

== DEINE OFFENEN ZIELE UND PROJEKTE ==
{_rows_to_text(goals, ("id", "title", "status", "due", "detail"))}

== OFFENE ZIELE ALLER AGENTEN (nur zur Orientierung) ==
{_rows_to_text(all_goals, ("agent", "title", "status", "due"))}

== DEINE LETZTEN KENNZAHLEN ==
{_rows_to_text(metrics, ("metric", "value", "note", "timestamp"))}

== DEIN PROTOKOLL DER LETZTEN LAEUFE ==
{_rows_to_text(log, ("action", "result", "detail", "timestamp"))}

== NEUE NACHRICHTEN VON ROBERT ==
{inbox_text}

Antworte jetzt im vorgegebenen JSON-Format.""",
        handoff_ids,
        inbox_ids,
    )


def _apply_result(
    conn: sqlite3.Connection,
    config: Config,
    agent: str,
    trigger: str,
    data: dict[str, Any],
    allowed_handoff_ids: list[int],
    shown_inbox_ids: list[int],
) -> dict[str, int]:
    """Schreibt alles in einer einzigen Transaktion. Alles oder nichts."""
    applied = {
        "Zustaende": 0, "Uebergaben abgeschlossen": 0, "Uebergaben erstellt": 0,
        "Ziele": 0, "Kennzahlen": 0, "Check-in": 0,
    }
    allowed = set(allowed_handoff_ids)

    with db.transaction(conn):
        for entry in data.get("state_updates", []):
            key = str(entry.get("key", "")).strip()
            if not key:
                continue
            if db.set_state(conn, agent, key, str(entry.get("value", ""))):
                applied["Zustaende"] += 1
        if applied["Zustaende"]:
            db.snapshot_state(conn, agent, reason=trigger)

        for raw_id in data.get("processed_handoff_ids", []):
            try:
                handoff_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            # Nur was diesem Agenten wirklich vorgelegt wurde.
            if handoff_id in allowed and db.close_handoff(conn, handoff_id, agent):
                applied["Uebergaben abgeschlossen"] += 1

        for entry in data.get("handoffs", []):
            target = str(entry.get("target_agent", "")).strip()
            if target not in AGENTS or target == agent:
                continue
            db.add_handoff(
                conn, agent, target,
                entry.get("thread_key") or None,
                entry.get("type") or None,
                entry.get("facts") or None,
                entry.get("decision") or None,
                entry.get("next_step") or None,
            )
            applied["Uebergaben erstellt"] += 1

        for entry in data.get("goal_updates", []):
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            status = entry.get("status") or "open"
            if status not in STATUS_VALUES:
                status = "open"
            db.upsert_goal(
                conn, agent, title, status,
                entry.get("due") or None,
                entry.get("detail") or None,
            )
            applied["Ziele"] += 1

        for entry in data.get("metrics", []):
            metric = str(entry.get("metric", "")).strip()
            if not metric:
                continue
            try:
                value = float(entry.get("value"))
            except (TypeError, ValueError):
                continue
            db.add_metric(conn, agent, metric, value, entry.get("note") or None)
            applied["Kennzahlen"] += 1

        checkin_note = str(data.get("checkin_note", "")).strip()
        if checkin_note:
            db.save_checkin(conn, agent, local_date(config), {
                "trigger": trigger,
                "note": checkin_note,
                "summary": data.get("summary", ""),
            })
            applied["Check-in"] = 1

        db.mark_inbox_consumed(conn, shown_inbox_ids)

        db.log_execution(
            conn, agent, trigger, "ok",
            json.dumps({
                "summary": data.get("summary", ""),
                "applied": applied,
            }, ensure_ascii=False),
        )
    return applied


def run_agent(
    conn: sqlite3.Connection,
    config: Config,
    agent: str,
    trigger: str,
    ask: Callable[..., llm.LLMResult] | None = None,
    notify: Callable[[str], int] | None = None,
) -> AgentRun:
    """Fuehrt einen Agenten genau einmal aus."""
    if agent not in AGENTS:
        raise ValueError(f"Unbekannter Agent: {agent}")

    run = AgentRun(agent=agent, trigger=trigger, ok=False)
    try:
        system = load_system_prompt(agent)
        user, handoff_ids, inbox_ids = build_context(conn, config, agent, trigger)

        if config.dry_run and ask is None:
            run.ok = True
            run.summary = "Testmodus: Kein KI-Aufruf, keine Aenderung."
            run.telegram_text = ""
            return run

        ask_fn = ask or (lambda **kwargs: llm.ask_json(**kwargs))
        result = ask_fn(
            api_key=config.anthropic_api_key,
            model=config.model,
            effort=config.effort,
            system=system,
            user=user,
            schema=RESPONSE_SCHEMA,
        )
        run.cost_note = result.cost_note

        run.applied = _apply_result(
            conn, config, agent, trigger, result.data, handoff_ids, inbox_ids
        )
        run.summary = str(result.data.get("summary", "")).strip()
        run.ok = True

        message = str(result.data.get("telegram_message", "")).strip()
        if message:
            label = AGENT_LABELS.get(agent, agent)
            changes = ", ".join(f"{k}: {v}" for k, v in run.applied.items() if v)
            footer = f"\n\n({changes})" if changes else ""
            run.telegram_text = f"{label} - {trigger}\n\n{message}{footer}"
            if not config.dry_run:
                sender = notify or (
                    lambda text: telegram.send_message(
                        config.telegram_bot_token, config.telegram_chat_id, text
                    )
                )
                try:
                    sender(run.telegram_text)
                    run.telegram_sent = True
                except Exception as exc:
                    # Die Daten sind gespeichert, nur der Versand scheiterte.
                    # Das wird ehrlich protokolliert statt verschwiegen.
                    with db.transaction(conn):
                        db.log_execution(
                            conn, agent, trigger, "telegram_fehler", str(exc)
                        )
                    run.error = f"Gespeichert, aber Telegram-Versand fehlgeschlagen: {exc}"
        return run

    except Exception as exc:
        run.ok = False
        run.error = f"{type(exc).__name__}: {exc}"
        try:
            with db.transaction(conn):
                db.log_execution(conn, agent, trigger, "fehler", run.error)
        except Exception:  # pragma: no cover - Datenbank selbst kaputt
            pass
        return run
