"""Bedienung von Robert-OS ueber die Kommandozeile.

Aufruf:  python3 -m robertos <befehl>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import agents as agents_mod
from . import db, jobs, llm, telegram
from .config import AGENT_LABELS, AGENTS, ConfigError, load_config


def _open_db(config):
    if not config.db_path.exists():
        return db.init_db(config.db_path)
    return db.connect(config.db_path)


def cmd_init(args) -> int:
    config = load_config()
    db.init_db(config.db_path)
    print(f"Datenbank ist bereit: {config.db_path}")
    print("Tabellen: current_states, state_history, handoffs, checkins,")
    print("          metrics_log, goals_projects, execution_log, inbox, kv")
    return 0


def cmd_doctor(args) -> int:
    """Prueft der Reihe nach alles durch und sagt genau, was noch fehlt."""
    config = load_config()
    problems = 0

    print("== Robert-OS Selbsttest ==\n")

    print("1. Datenbank")
    try:
        conn = _open_db(config)
        tables = [
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        print(f"   OK - {config.db_path} mit {len(tables)} Tabellen")
    except Exception as exc:
        print(f"   FEHLER - {exc}")
        problems += 1

    print("2. Rollentexte der Agenten")
    for agent in AGENTS:
        try:
            text = agents_mod.load_system_prompt(agent)
            print(f"   OK - {AGENT_LABELS[agent]} ({len(text)} Zeichen)")
        except Exception as exc:
            print(f"   FEHLER - {AGENT_LABELS[agent]}: {exc}")
            problems += 1

    print("3. Anthropic API-Key")
    if not config.anthropic_api_key:
        print("   FEHLT - ANTHROPIC_API_KEY ist in .env noch leer")
        problems += 1
    else:
        print(f"   Eingetragen (endet auf ...{config.anthropic_api_key[-4:]})")
        print("   Echten Testaufruf machen mit: python3 -m robertos test-api")

    print("4. Telegram")
    if not config.telegram_bot_token:
        print("   FEHLT - TELEGRAM_BOT_TOKEN ist in .env noch leer")
        problems += 1
    else:
        try:
            me = telegram.get_me(config.telegram_bot_token)
            print(f"   OK - Bot erreichbar: @{me.get('username')}")
        except Exception as exc:
            print(f"   FEHLER - {exc}")
            problems += 1
        if not config.telegram_chat_id:
            print("   FEHLT - TELEGRAM_CHAT_ID ist leer. Ermitteln mit: "
                  "python3 -m robertos chat-id")
            problems += 1
        else:
            print(f"   Chat-ID eingetragen: {config.telegram_chat_id}")

    print("\n5. Einstellungen")
    print(f"   Modell:    {config.model}")
    print(f"   Gruendlichkeit: {config.effort}")
    print(f"   Zeitzone:  {config.timezone}")
    print(f"   Testmodus: {'AN (nichts wird wirklich gesendet)' if config.dry_run else 'aus'}")

    print()
    if problems:
        print(f"Ergebnis: {problems} Punkt(e) offen. Siehe oben.")
        return 1
    print("Ergebnis: Alles in Ordnung. Das System ist einsatzbereit.")
    return 0


def cmd_chat_id(args) -> int:
    """Findet die persoenliche Chat-ID heraus."""
    config = load_config()
    if not config.telegram_bot_token:
        print("Es fehlt der TELEGRAM_BOT_TOKEN in der Datei .env.")
        return 1
    me = telegram.get_me(config.telegram_bot_token)
    print(f"Bot gefunden: @{me.get('username')}")
    print()
    print("Jetzt in Telegram diesem Bot irgendeine Nachricht schicken,")
    print("zum Beispiel 'hallo'. Danach diesen Befehl erneut ausfuehren.")
    print()
    updates = telegram.get_updates(config.telegram_bot_token)
    found = {}
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            found[str(chat["id"])] = chat.get("first_name") or chat.get("title") or "?"
    if not found:
        print("Noch keine Nachricht gefunden. Schick dem Bot eine Nachricht "
              "und versuch es gleich nochmal.")
        return 1
    for chat_id, name in found.items():
        print(f"Gefunden: {name} -> Chat-ID {chat_id}")
    print()
    print("Trage diese Zahl in der Datei .env bei TELEGRAM_CHAT_ID ein.")
    return 0


def cmd_test_telegram(args) -> int:
    config = load_config()
    token, chat_id = config.require_telegram()
    parts = telegram.send_message(
        token, chat_id,
        "Robert-OS meldet sich. Die Verbindung zu deinem Handy steht.",
    )
    print(f"Nachricht versendet ({parts} Teil(e)). Schau auf dein Handy.")
    return 0


def cmd_test_api(args) -> int:
    config = load_config()
    key = config.require_anthropic()
    result = llm.ask_json(
        api_key=key,
        model=config.model,
        effort="low",
        system="Du antwortest knapp auf Deutsch.",
        user="Antworte mit einem kurzen Satz, dass die Verbindung steht.",
        schema={
            "type": "object",
            "properties": {"antwort": {"type": "string"}},
            "required": ["antwort"],
            "additionalProperties": False,
        },
        max_tokens=1000,
    )
    print(f"Antwort der KI: {result.data.get('antwort')}")
    print(f"Modell: {result.model}")
    print(f"Verbrauch: {result.cost_note}")
    for note in result.notes:
        print(f"Hinweis: {note}")
    return 0


def cmd_agent(args) -> int:
    config = load_config()
    conn = _open_db(config)
    run = agents_mod.run_agent(conn, config, args.name, args.trigger)
    print(run.describe())
    if run.telegram_text:
        print("\n--- Nachricht ---")
        print(run.telegram_text)
    return 0 if run.ok and not run.error else 1


def cmd_job(args) -> int:
    config = load_config()
    conn = _open_db(config)
    runs = jobs.run_job(conn, config, args.name)
    failed = 0
    for run in runs:
        print(run.describe())
        if run.error:
            failed += 1
    return 1 if failed else 0


def cmd_note(args) -> int:
    """Legt eine Nachricht in den Posteingang, die der naechste Lauf liest."""
    config = load_config()
    conn = _open_db(config)
    text = " ".join(args.text).strip()
    if not text:
        print("Kein Text angegeben.")
        return 1
    with db.transaction(conn):
        note_id = db.add_inbox(conn, "cli", text)
    print(f"Notiz gespeichert (id {note_id}). Der naechste Agentenlauf sieht sie.")
    return 0


def cmd_poll(args) -> int:
    config = load_config()
    conn = _open_db(config)
    count = jobs.poll_telegram(conn, config)
    print(f"{count} neue Nachricht(en) aus Telegram uebernommen.")
    return 0


def cmd_status(args) -> int:
    config = load_config()
    conn = _open_db(config)
    print("== Zustand von Robert-OS ==\n")
    for agent in AGENTS:
        states = db.get_states(conn, agent)
        open_h = db.open_handoffs(conn, agent)
        goals = db.open_goals(conn, agent)
        print(f"{AGENT_LABELS[agent]}")
        print(f"  Zustaende: {len(states)} | offene Uebergaben: {len(open_h)} "
              f"| offene Ziele: {len(goals)}")
        for key, value in list(states.items())[:5]:
            shown = value if len(value) <= 90 else value[:87] + "..."
            print(f"    {key}: {shown}")
        for row in open_h[:3]:
            print(f"    <- von {row['source_agent']}: {row['next_step']}")
        print()

    print("Letzte Laeufe:")
    rows = conn.execute(
        "SELECT agent, action, result, timestamp FROM execution_log "
        "ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if not rows:
        print("  (noch keine)")
    for row in rows:
        print(f"  {row['timestamp']} | {AGENT_LABELS.get(row['agent'], row['agent'])} "
              f"| {row['action']} | {row['result']}")

    inbox = db.unread_inbox(conn)
    print(f"\nUngelesene Nachrichten im Posteingang: {len(inbox)}")
    return 0


def cmd_jobs(args) -> int:
    print("Verfuegbare Jobs:\n")
    for name, (trigger, agent_list) in jobs.JOBS.items():
        print(f"  {name:16s} {jobs.JOB_DESCRIPTIONS.get(name, '')}")
        print(f"  {'':16s} Anlass: {trigger}")
        print(f"  {'':16s} Agenten: "
              f"{' -> '.join(AGENT_LABELS[a] for a in agent_list)}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="robertos", description="Robert-OS: vier Agenten, die rund um die Uhr laufen."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Datenbank anlegen").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="Alles durchpruefen").set_defaults(func=cmd_doctor)
    sub.add_parser("chat-id", help="Telegram-Chat-ID herausfinden").set_defaults(func=cmd_chat_id)
    sub.add_parser("test-telegram", help="Testnachricht aufs Handy").set_defaults(func=cmd_test_telegram)
    sub.add_parser("test-api", help="Verbindung zur KI testen").set_defaults(func=cmd_test_api)
    sub.add_parser("status", help="Aktuellen Stand anzeigen").set_defaults(func=cmd_status)
    sub.add_parser("jobs", help="Alle Jobs auflisten").set_defaults(func=cmd_jobs)
    sub.add_parser("poll", help="Telegram-Nachrichten abholen").set_defaults(func=cmd_poll)

    p_agent = sub.add_parser("agent", help="Einen einzelnen Agenten starten")
    p_agent.add_argument("name", choices=list(AGENTS))
    p_agent.add_argument("--trigger", default="Manueller Start")
    p_agent.set_defaults(func=cmd_agent)

    p_job = sub.add_parser("job", help="Einen geplanten Lauf starten")
    p_job.add_argument("name", choices=sorted(jobs.JOBS))
    p_job.set_defaults(func=cmd_job)

    p_note = sub.add_parser("note", help="Notiz fuer den naechsten Lauf hinterlegen")
    p_note.add_argument("text", nargs="+")
    p_note.set_defaults(func=cmd_note)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Fehlende Angabe: {exc}")
        return 1
    except (llm.LLMError, telegram.TelegramError) as exc:
        print(f"Fehler: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
