"""Anbindung an die Anthropic-Schnittstelle (die KI hinter den Agenten).

Der Hintergrunddienst kann sich nicht in einen Chat einloggen, deshalb
laeuft alles ueber die offizielle Schnittstelle mit API-Key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Preise in US-Dollar pro einer Million Textbausteine ("Tokens").
# Nur fuer die Kostenschaetzung im Protokoll, nicht fuer die Abrechnung.
PRICES_PER_MTOK = {
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """Die KI konnte nicht befragt werden oder lieferte keine brauchbare Antwort."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    model: str = ""
    raw_text: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def estimated_cost_usd(self) -> float:
        price_in, price_out = PRICES_PER_MTOK.get(self.model, (5.0, 25.0))
        return (
            self.input_tokens / 1_000_000 * price_in
            + self.output_tokens / 1_000_000 * price_out
        )

    @property
    def cost_note(self) -> str:
        return (
            f"{self.input_tokens} rein / {self.output_tokens} raus, "
            f"ca. {self.estimated_cost_usd * 100:.2f} US-Cent"
        )


def _extract_text(message: Any) -> str:
    for block in message.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise LLMError("Die KI hat keinen Text zurueckgegeben.")


def ask_json(
    api_key: str,
    model: str,
    effort: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 8000,
) -> LLMResult:
    """Stellt der KI eine Frage und erzwingt eine Antwort im festen Format.

    Das feste Format ist wichtig: So kann das Programm die Antwort
    zuverlaessig weiterverarbeiten, statt Fliesstext raten zu muessen.
    """
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - nur ohne Installation
        raise LLMError(
            "Die Bibliothek 'anthropic' fehlt. Installiere sie mit: "
            "pip install -r requirements.txt"
        ) from exc

    client = anthropic.Anthropic(api_key=api_key, timeout=300.0)
    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": schema},
    }
    if effort:
        output_config["effort"] = effort

    common: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": output_config,
    }

    notes: list[str] = []
    try:
        # Sicherheitsnetz: Falls das Modell eine Anfrage ablehnt, uebernimmt
        # automatisch ein Ersatzmodell, statt den Lauf platzen zu lassen.
        message = client.beta.messages.create(
            betas=[REFUSAL_FALLBACK_BETA], fallbacks="default", **common
        )
    except anthropic.BadRequestError:
        notes.append("Ersatzmodell-Funktion nicht verfuegbar, normaler Aufruf benutzt.")
        message = client.messages.create(**common)
    except anthropic.AuthenticationError as exc:
        raise LLMError(
            "Der Anthropic API-Key wurde nicht akzeptiert. Bitte den Wert von "
            "ANTHROPIC_API_KEY in der Datei .env pruefen."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Anthropic bremst gerade (Rate Limit). Spaeter erneut versuchen.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic meldete Fehler {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"Keine Verbindung zu Anthropic: {exc}") from exc

    stop_reason = getattr(message, "stop_reason", "") or ""
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LLMError(f"Die KI hat die Anfrage abgelehnt (Kategorie: {category}).")
    if stop_reason == "max_tokens":
        notes.append("Antwort war zu lang und wurde abgeschnitten.")

    text = _extract_text(message)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Antwort der KI war kein gueltiges JSON: {text[:400]}") from exc

    usage = getattr(message, "usage", None)
    return LLMResult(
        data=data,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        stop_reason=stop_reason,
        model=getattr(message, "model", model) or model,
        raw_text=text,
        notes=notes,
    )
