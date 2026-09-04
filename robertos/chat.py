"""Das Gespraech mit den Agenten.

Robert schreibt in Telegram, und der zustaendige Agent antwortet sofort.
Wer zustaendig ist, entscheidet entweder Robert selbst (mit @sales, @chef
und so weiter) oder der Stabschef.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Callable

from . import agents as agents_mod
from . import db, llm
from .config import AGENT_LABELS, AGENTS, Config

# Kurzformen, mit denen Robert einen Agenten direkt anspricht.
KUERZEL: dict[str, str] = {
    "chef": "robert_os_main",
    "robert": "robert_os_main",
    "os": "robert_os_main",
    "stabschef": "robert_os_main",
    "sales": "sales_main",
    "vertrieb": "sales_main",
    "verkauf": "sales_main",
    "performance": "performance_main",
    "koerper": "performance_main",
    "körper": "performance_main",
    "energie": "performance_main",
    "reality": "reality_check_main",
    "check": "reality_check_main",
    "realitycheck": "reality_check_main",
}

ZUSTAENDIGKEITEN = {
    "robert_os_main": "Tagessteuerung, Prioritaeten, Nachhalten, Wochenplanung, "
                      "alles Uebergreifende und alles, was sonst nirgends passt",
    "sales_main": "Kunden, Kontakte, Angebote, Nachfassen, Abschluesse, Umsatz",
    "performance_main": "Schlaf, Bewegung, Ernaehrung, Energie, Konzentration, Erholung",
    "reality_check_main": "Faktencheck, Selbstbetrug aufdecken, liegengebliebene "
                          "Vorhaben, Widersprueche zwischen Ankuendigung und Datenlage",
}

ROUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "enum": list(AGENTS)},
        "begruendung": {"type": "string"},
    },
    "required": ["agent", "begruendung"],
    "additionalProperties": False,
}

ROUTER_SYSTEM = """Du bist der Stabschef von Robert-OS. Deine einzige Aufgabe
ist zu entscheiden, welcher der vier Agenten eine Nachricht von Robert
beantworten soll. Du antwortest nicht selbst.

Die vier Agenten und ihre Zustaendigkeit:
""" + "\n".join(
    f"- {name} ({AGENT_LABELS[name]}): {beschreibung}"
    for name, beschreibung in ZUSTAENDIGKEITEN.items()
) + """

Regeln:
- Waehle genau einen Agenten.
- Im Zweifel robert_os_main. Der ist fuer alles Uebergreifende zustaendig.
- Beziehe dich auf den bisherigen Gespraechsverlauf. Wenn Robert offensichtlich
  ein laufendes Thema fortsetzt, bleibt derselbe Agent zustaendig.
"""


def erkenne_kuerzel(text: str) -> tuple[str | None, str]:
    """Prueft, ob Robert einen Agenten direkt angesprochen hat.

    Gibt den Agenten und den um die Anrede bereinigten Text zurueck.
    """
    gestrafft = text.strip()
    if not gestrafft.startswith("@"):
        return None, text
    erstes, _, rest = gestrafft.partition(" ")
    schluessel = erstes[1:].strip().lower().rstrip(":,")
    agent = KUERZEL.get(schluessel)
    if agent is None:
        return None, text
    return agent, rest.strip() or text


def verlauf_als_text(zeilen: list[sqlite3.Row]) -> str:
    if not zeilen:
        return "  (noch kein Gespraech)"
    ausgabe = []
    for zeile in zeilen:
        if zeile["rolle"] == "robert":
            ausgabe.append(f"  Robert: {zeile['text']}")
        else:
            name = AGENT_LABELS.get(zeile["agent"] or "", zeile["agent"] or "Agent")
            ausgabe.append(f"  {name}: {zeile['text']}")
    return "\n".join(ausgabe)


def waehle_agent(
    conn: sqlite3.Connection,
    config: Config,
    chat_id: str,
    text: str,
    ask: Callable[..., llm.LLMResult] | None = None,
) -> tuple[str, str]:
    """Bestimmt den zustaendigen Agenten. Gibt Agent und Begruendung zurueck."""
    direkt, _ = erkenne_kuerzel(text)
    if direkt:
        return direkt, "von Robert direkt angesprochen"

    verlauf = verlauf_als_text(db.recent_messages(conn, chat_id, limit=6))
    ask_fn = ask or (lambda **kwargs: llm.ask_json(**kwargs))
    try:
        ergebnis = ask_fn(
            api_key=config.anthropic_api_key,
            model=config.model,
            effort="low",
            system=ROUTER_SYSTEM,
            user=f"== BISHERIGES GESPRAECH ==\n{verlauf}\n\n"
                 f"== NEUE NACHRICHT VON ROBERT ==\n{text}",
            schema=ROUTER_SCHEMA,
            max_tokens=1000,
        )
        agent = str(ergebnis.data.get("agent", "")).strip()
        if agent in AGENTS:
            return agent, str(ergebnis.data.get("begruendung", ""))
    except llm.LLMError:
        pass
    # Wenn die Zuordnung scheitert, uebernimmt der Chef.
    return "robert_os_main", "Zuordnung nicht moeglich, Chef uebernimmt"


def beantworte(
    conn: sqlite3.Connection,
    config: Config,
    chat_id: str,
    text: str,
    ask: Callable[..., llm.LLMResult] | None = None,
    notify: Callable[[str], int] | None = None,
) -> agents_mod.AgentRun:
    """Nimmt eine Nachricht von Robert entgegen und laesst sie beantworten."""
    with db.transaction(conn):
        db.add_message(conn, chat_id, "robert", text)

    agent, begruendung = waehle_agent(conn, config, chat_id, text, ask=ask)
    _, reine_frage = erkenne_kuerzel(text)

    verlauf = verlauf_als_text(db.recent_messages(conn, chat_id, limit=12))
    zusatz = f"""
== BISHERIGES GESPRAECH MIT ROBERT ==
{verlauf}

== ROBERT SCHREIBT DIR GERADE DIREKT ==
{reine_frage}

Das ist ein Gespraech, kein geplanter Lauf. Antworte in
`telegram_message` unmittelbar auf diese Nachricht, so wie ein Mensch
antworten wuerde: knapp, konkret, ohne Ueberschrift und ohne
Statusbericht. Wenn du etwas nicht weisst, frag nach.
Zustaendigkeit wurde dir zugewiesen: {begruendung}
"""

    lauf = agents_mod.run_agent(
        conn, config, agent, "Chat",
        ask=ask, notify=notify, zusatz=zusatz, im_gespraech=True,
    )

    if lauf.antwort:
        with db.transaction(conn):
            db.add_message(conn, chat_id, "agent", lauf.antwort, agent=agent)
    return lauf
