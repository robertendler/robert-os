#!/usr/bin/env bash
# Einmalige Einrichtung auf dem Oracle-Cloud-Server (Ubuntu).
# Aufruf im Projektordner:  bash scripts/setup_server.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "== 1/6 Systempakete aktualisieren =="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip cron sqlite3
sudo systemctl enable --now cron

echo "== 2/6 Zeitzone auf Europe/Berlin stellen =="
sudo timedatectl set-timezone Europe/Berlin
date

echo "== 3/6 Abgeschottete Python-Umgebung anlegen =="
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "== 4/6 Zugangsdaten-Datei vorbereiten =="
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Die Datei .env wurde angelegt."
  echo "Jetzt mit 'nano .env' die Zugangsdaten eintragen."
else
  chmod 600 .env
  echo "Die Datei .env existiert bereits, sie wird nicht ueberschrieben."
fi

echo "== 5/6 Datenbank anlegen =="
./.venv/bin/python3 -m robertos init

echo "== 6/6 Selbsttest =="
./.venv/bin/python3 -m robertos doctor || true

echo
echo "Fertig. Naechste Schritte:"
echo "  1. nano .env                      (Zugangsdaten eintragen)"
echo "  2. ./.venv/bin/python3 -m robertos doctor"
echo "  3. bash scripts/install_cron.sh   (Zeitplan aktivieren)"
