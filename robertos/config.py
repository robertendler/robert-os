"""Liest die Zugangsdaten und Einstellungen aus der Datei .env ein.

Bewusst ohne Zusatzbibliothek, damit auf dem Server so wenig wie
moeglich installiert werden muss.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

AGENTS = (
    "robert_os_main",
    "sales_main",
    "performance_main",
    "reality_check_main",
)

AGENT_LABELS = {
    "robert_os_main": "Robert-OS Main",
    "sales_main": "Sales Main",
    "performance_main": "Performance Main",
    "reality_check_main": "Reality Check Main",
}


def load_env_file(path: Path = ENV_FILE) -> None:
    """Traegt die Werte aus .env in die Umgebungsvariablen ein.

    Bereits gesetzte Umgebungsvariablen gewinnen, damit man einzelne
    Werte fuer einen Testlauf ueberschreiben kann.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ConfigError(RuntimeError):
    """Wird ausgeloest, wenn eine noetige Angabe fehlt."""


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    model: str
    effort: str
    db_path: Path
    timezone: str
    dry_run: bool

    def require_anthropic(self) -> str:
        if not self.anthropic_api_key:
            raise ConfigError(
                "Es fehlt der Anthropic API-Key. Trage ihn in der Datei .env "
                "bei ANTHROPIC_API_KEY ein."
            )
        return self.anthropic_api_key

    def require_telegram(self) -> tuple[str, str]:
        if not self.telegram_bot_token:
            raise ConfigError(
                "Es fehlt der Telegram-Bot-Token. Trage ihn in der Datei .env "
                "bei TELEGRAM_BOT_TOKEN ein."
            )
        if not self.telegram_chat_id:
            raise ConfigError(
                "Es fehlt die Telegram-Chat-ID. Ermittle sie mit dem Befehl "
                "'robertos chat-id' und trage sie in .env ein."
            )
        return self.telegram_bot_token, self.telegram_chat_id


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "ja", "on"}


def load_config() -> Config:
    load_env_file()
    db_value = os.environ.get("ROBERTOS_DB", "data/robertos.db")
    db_path = Path(db_value)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return Config(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        model=os.environ.get("ROBERTOS_MODEL", "claude-opus-5").strip(),
        effort=os.environ.get("ROBERTOS_EFFORT", "medium").strip(),
        db_path=db_path,
        timezone=os.environ.get("ROBERTOS_TZ", "Europe/Berlin").strip(),
        dry_run=_as_bool(os.environ.get("ROBERTOS_DRY_RUN", "0")),
    )


def write_env_values(updates: dict[str, str], path: Path = ENV_FILE) -> Path:
    """Traegt Werte in die Datei .env ein, ohne den Rest anzufassen.

    Existiert noch keine .env, wird .env.example als Vorlage benutzt.
    Die Datei bekommt Rechte 600: nur der Besitzer darf sie lesen.
    """
    template = PROJECT_ROOT / ".env.example"
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    elif template.exists():
        lines = template.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    remaining = dict(updates)
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                result.append(f"{key}={remaining.pop(key)}")
                continue
        result.append(line)

    if remaining:
        result.append("")
        for key, value in remaining.items():
            result.append(f"{key}={value}")

    path.write_text("\n".join(result).rstrip() + "\n", encoding="utf-8")
    path.chmod(0o600)

    # Damit die neuen Werte sofort im laufenden Programm gelten.
    for key, value in updates.items():
        os.environ[key] = value
    return path
