"""Telegram-Anbindung: schickt echte Push-Nachrichten aufs Handy.

Bewusst nur mit Bordmitteln von Python gebaut, damit auf dem Server
keine weitere Bibliothek noetig ist.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.telegram.org"
MAX_LENGTH = 4000  # Telegram erlaubt 4096 Zeichen, wir lassen Luft.


class TelegramError(RuntimeError):
    """Telegram hat die Nachricht nicht angenommen."""


def _call(token: str, method: str, params: dict[str, Any], timeout: float = 20.0) -> Any:
    url = f"{API_BASE}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise TelegramError(f"Telegram antwortete mit Fehler {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"Telegram nicht erreichbar: {exc.reason}") from exc
    if not payload.get("ok"):
        raise TelegramError(f"Telegram lehnte den Aufruf ab: {payload}")
    return payload["result"]


def split_message(text: str, limit: int = MAX_LENGTH) -> list[str]:
    """Teilt lange Texte an Zeilengrenzen in mehrere Nachrichten auf."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


def send_message(token: str, chat_id: str, text: str) -> int:
    """Sendet eine Nachricht. Gibt die Anzahl der versendeten Teile zurueck.

    Loest bei Misserfolg eine Ausnahme aus. Es wird also nie faelschlich
    behauptet, eine Nachricht sei rausgegangen.
    """
    parts = split_message(text)
    for part in parts:
        _call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": "true",
        })
    return len(parts)


def get_me(token: str) -> dict[str, Any]:
    """Prueft den Token und gibt die Bot-Daten zurueck."""
    return _call(token, "getMe", {})


def get_updates(token: str, offset: int | None = None, timeout: float = 20.0) -> list[dict[str, Any]]:
    """Holt neue Nachrichten ab, die an den Bot geschickt wurden."""
    params: dict[str, Any] = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    return _call(token, "getUpdates", params, timeout=timeout)
