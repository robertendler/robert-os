"""Datenbankzugriff fuer Robert-OS.

Wichtigster Punkt: Jede Aenderung laeuft in einer echten Transaktion.
Entweder wird alles geschrieben oder gar nichts. Ein halb geschriebener
Zustand kann nicht entstehen.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"


def now_iso() -> str:
    """Aktueller Zeitpunkt als Text, immer in UTC, immer gleich formatiert."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    """Oeffnet die Datenbank und stellt sie auf sicheren Mehrfachzugriff."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Legt die Tabellen an, falls sie noch nicht existieren."""
    conn = connect(db_path)
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Klammert Schreibvorgaenge in BEGIN / COMMIT beziehungsweise ROLLBACK.

    BEGIN IMMEDIATE sperrt die Datenbank sofort zum Schreiben. Zwei
    gleichzeitig laufende Agenten koennen sich damit nicht gegenseitig
    ueberschreiben - der zweite wartet, statt Unsinn zu schreiben.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# ---------------------------------------------------------------------
# Zustaende
# ---------------------------------------------------------------------

def set_state(conn: sqlite3.Connection, agent: str, key: str, value: str) -> bool:
    """Setzt einen Zustandswert. Gibt True zurueck, wenn sich etwas geaendert hat.

    Die Versionsnummer zaehlt bei jeder echten Aenderung hoch. So ist
    nachvollziehbar, wie oft ein Wert angefasst wurde.
    """
    row = conn.execute(
        "SELECT id, value FROM current_states WHERE agent = ? AND key = ?",
        (agent, key),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO current_states (agent, key, value, version, updated_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (agent, key, value, now_iso()),
        )
        return True
    if row["value"] == value:
        return False
    conn.execute(
        "UPDATE current_states SET value = ?, version = version + 1, "
        "updated_at = ? WHERE id = ?",
        (value, now_iso(), row["id"]),
    )
    return True


def get_states(conn: sqlite3.Connection, agent: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key, value FROM current_states WHERE agent = ? ORDER BY key",
        (agent,),
    ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def snapshot_state(conn: sqlite3.Connection, agent: str, reason: str) -> None:
    """Legt eine Kopie aller Zustaende dieses Agenten in der Historie ab."""
    snapshot = json.dumps(get_states(conn, agent), ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO state_history (agent, snapshot, changed_at, reason) "
        "VALUES (?, ?, ?, ?)",
        (agent, snapshot, now_iso(), reason),
    )


# ---------------------------------------------------------------------
# Uebergaben zwischen Agenten
# ---------------------------------------------------------------------

def add_handoff(
    conn: sqlite3.Connection,
    source_agent: str,
    target_agent: str,
    thread_key: str | None,
    type_: str | None,
    facts: str | None,
    decision: str | None,
    next_step: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO handoffs (source_agent, target_agent, thread_key, type, "
        "status, facts, decision, next_step, created_at) "
        "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)",
        (source_agent, target_agent, thread_key, type_, facts, decision,
         next_step, now_iso()),
    )
    return int(cur.lastrowid)


def open_handoffs(conn: sqlite3.Connection, target_agent: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM handoffs WHERE target_agent = ? AND status = 'open' "
        "ORDER BY id",
        (target_agent,),
    ).fetchall()


def close_handoff(conn: sqlite3.Connection, handoff_id: int, agent: str) -> bool:
    """Schliesst eine Uebergabe ab - aber nur, wenn sie wirklich an diesen
    Agenten gerichtet und noch offen ist. Verhindert, dass ein Agent fremde
    oder schon erledigte Eintraege als erledigt markiert."""
    cur = conn.execute(
        "UPDATE handoffs SET status = 'done', processed_at = ? "
        "WHERE id = ? AND target_agent = ? AND status = 'open'",
        (now_iso(), handoff_id, agent),
    )
    return cur.rowcount == 1


# ---------------------------------------------------------------------
# Check-ins, Kennzahlen, Ziele, Protokoll
# ---------------------------------------------------------------------

def save_checkin(conn: sqlite3.Connection, agent: str, date: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO checkins (agent, date, data, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (agent, date) DO UPDATE SET data = excluded.data",
        (agent, date, payload, now_iso()),
    )


def add_metric(
    conn: sqlite3.Connection, agent: str, metric: str, value: float, note: str | None = None
) -> int:
    cur = conn.execute(
        "INSERT INTO metrics_log (agent, metric, value, note, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (agent, metric, float(value), note, now_iso()),
    )
    return int(cur.lastrowid)


def upsert_goal(
    conn: sqlite3.Connection,
    agent: str,
    title: str,
    status: str = "open",
    due: str | None = None,
    detail: str | None = None,
) -> int:
    ts = now_iso()
    conn.execute(
        "INSERT INTO goals_projects (agent, title, status, due, detail, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (agent, title) DO UPDATE SET status = excluded.status, "
        "due = COALESCE(excluded.due, goals_projects.due), "
        "detail = COALESCE(excluded.detail, goals_projects.detail), "
        "updated_at = excluded.updated_at",
        (agent, title, status, due, detail, ts, ts),
    )
    row = conn.execute(
        "SELECT id FROM goals_projects WHERE agent = ? AND title = ?", (agent, title)
    ).fetchone()
    return int(row["id"])


def open_goals(conn: sqlite3.Connection, agent: str | None = None) -> list[sqlite3.Row]:
    if agent:
        return conn.execute(
            "SELECT * FROM goals_projects WHERE agent = ? AND status != 'done' "
            "ORDER BY COALESCE(due, '9999'), id",
            (agent,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM goals_projects WHERE status != 'done' "
        "ORDER BY COALESCE(due, '9999'), id"
    ).fetchall()


def log_execution(
    conn: sqlite3.Connection, agent: str, action: str, result: str, detail: str | None = None
) -> int:
    cur = conn.execute(
        "INSERT INTO execution_log (agent, action, result, detail, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (agent, action, result, detail, now_iso()),
    )
    return int(cur.lastrowid)


def recent_log(conn: sqlite3.Connection, agent: str, limit: int = 15) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM execution_log WHERE agent = ? ORDER BY id DESC LIMIT ?",
        (agent, limit),
    ).fetchall()


def recent_metrics(conn: sqlite3.Connection, agent: str, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM metrics_log WHERE agent = ? ORDER BY id DESC LIMIT ?",
        (agent, limit),
    ).fetchall()


# ---------------------------------------------------------------------
# Posteingang (was Robert per Telegram schreibt)
# ---------------------------------------------------------------------

def add_inbox(conn: sqlite3.Connection, source: str, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO inbox (source, text, created_at) VALUES (?, ?, ?)",
        (source, text, now_iso()),
    )
    return int(cur.lastrowid)


def unread_inbox(conn: sqlite3.Connection, limit: int = 25) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM inbox WHERE consumed_at IS NULL ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def mark_inbox_consumed(conn: sqlite3.Connection, ids: list[int]) -> None:
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"UPDATE inbox SET consumed_at = ? WHERE id IN ({placeholders}) "
        "AND consumed_at IS NULL",
        [now_iso(), *ids],
    )


# ---------------------------------------------------------------------
# Interne Merkzettel
# ---------------------------------------------------------------------

def kv_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------------
# Gespraechsverlauf
# ---------------------------------------------------------------------

def add_message(
    conn: sqlite3.Connection, chat_id: str, rolle: str, text: str,
    agent: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO messages (chat_id, rolle, agent, text, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(chat_id), rolle, agent, text, now_iso()),
    )
    return int(cur.lastrowid)


def recent_messages(
    conn: sqlite3.Connection, chat_id: str, limit: int = 12
) -> list[sqlite3.Row]:
    """Die letzten Nachrichten, aelteste zuerst."""
    rows = conn.execute(
        "SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (str(chat_id), limit),
    ).fetchall()
    return list(reversed(rows))
