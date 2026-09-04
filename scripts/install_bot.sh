#!/usr/bin/env bash
# Richtet den Dauerdienst ein, der auf Telegram-Nachrichten antwortet.
# Der Dienst startet automatisch mit dem Server und wird bei einem
# Absturz neu gestartet.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENUTZER="$(id -un)"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

[ -x "$PYTHON" ] || { echo "FEHLER: $PYTHON fehlt. Erst setup_server.sh laufen lassen."; exit 1; }

echo "== Dienst einrichten =="
sudo tee /etc/systemd/system/robert-os-bot.service >/dev/null <<UNIT
[Unit]
Description=Robert-OS Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BENUTZER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON -m robertos bot
Restart=always
RestartSec=10
StandardOutput=append:$PROJECT_DIR/logs/bot.log
StandardError=append:$PROJECT_DIR/logs/bot.log

[Install]
WantedBy=multi-user.target
UNIT

mkdir -p "$PROJECT_DIR/logs"
sudo systemctl daemon-reload
sudo systemctl enable --now robert-os-bot

sleep 3
echo
echo "== Zustand =="
sudo systemctl status robert-os-bot --no-pager --lines=8 || true
echo
echo "Fertig. Schreib deinem Bot in Telegram eine Nachricht."
echo
echo "Nuetzliche Befehle:"
echo "  sudo systemctl status robert-os-bot     Laeuft er?"
echo "  sudo systemctl restart robert-os-bot    Neu starten"
echo "  tail -f logs/bot.log                    Mitlesen, was er tut"
