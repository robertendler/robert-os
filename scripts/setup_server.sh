#!/usr/bin/env bash
# Einmalige Einrichtung auf dem Server.
# Laeuft auf Ubuntu/Debian und auf Oracle Linux / RHEL / Fedora.
# Aufruf im Projektordner:  bash scripts/setup_server.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# --- Betriebssystem erkennen -----------------------------------------
if command -v apt-get >/dev/null 2>&1; then
  FAMILIE="debian"
  CRON_DIENST="cron"
elif command -v dnf >/dev/null 2>&1; then
  FAMILIE="redhat"
  CRON_DIENST="crond"
else
  echo "FEHLER: Weder apt-get noch dnf gefunden."
  echo "Dieses Skript unterstuetzt Ubuntu/Debian und Oracle Linux/RHEL."
  exit 1
fi
echo "Erkanntes System: $FAMILIE"

# --- Auslagerungsspeicher ---------------------------------------------
# Die kostenlose Oracle-Maschine hat nur 1 GB Arbeitsspeicher. Der
# Paketmanager braucht beim Sortieren seiner Paketlisten kurzzeitig mehr
# und wird sonst vom System abgeschossen ("Killed"). Eine Auslagerungs-
# datei auf der Festplatte faengt diese Spitzen ab.
speicher_absichern() {
  local ram_mb swap_mb
  ram_mb=$(free -m | awk '/^Mem:/ {print $2}')
  swap_mb=$(free -m | awk '/^Swap:/ {print $2}')

  if [ "${ram_mb:-0}" -ge 2000 ] || [ "${swap_mb:-0}" -ge 1000 ]; then
    echo "Arbeitsspeicher reicht (${ram_mb} MB RAM, ${swap_mb} MB Auslagerung)."
    return 0
  fi

  echo "Nur ${ram_mb} MB Arbeitsspeicher. Lege 2 GB Auslagerungsdatei an ..."
  if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile 2>/dev/null \
      || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
  fi
  sudo swapon /swapfile 2>/dev/null || true
  grep -q '^/swapfile' /etc/fstab \
    || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  echo "Erledigt:"
  free -h | sed 's/^/   /'
}

echo "== 0/6 Arbeitsspeicher pruefen =="
speicher_absichern

echo "== 1/6 Systempakete installieren =="
if [ "$FAMILIE" = "debian" ]; then
  sudo apt-get update -y
  sudo apt-get install -y python3 python3-venv python3-pip cron sqlite3
  PYTHON_BIN="python3"
else
  sudo dnf install -y python3.11 python3.11-pip sqlite cronie \
    || sudo dnf install -y python3 python3-pip sqlite cronie
  # Neuere Python-Fassung bevorzugen, falls vorhanden.
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
  else
    PYTHON_BIN="python3"
  fi
fi
sudo systemctl enable --now "$CRON_DIENST"
echo "Benutzte Python-Fassung: $($PYTHON_BIN --version)"

echo "== 2/6 Zeitzone auf Europe/Berlin stellen =="
sudo timedatectl set-timezone Europe/Berlin
date

echo "== 3/6 Abgeschottete Python-Umgebung anlegen =="
"$PYTHON_BIN" -m venv .venv
./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "== 4/6 Zugangsdaten-Datei vorbereiten =="
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Die Datei .env wurde angelegt."
else
  chmod 600 .env
  echo "Die Datei .env existiert bereits, sie wird nicht ueberschrieben."
fi

echo "== 5/6 Datenbank anlegen =="
./.venv/bin/python3 -m robertos init

echo "== 6/6 Selbsttest =="
./.venv/bin/python3 -m robertos doctor || true

echo
echo "Fertig. Naechster Schritt - Zugangsdaten eintragen:"
echo "  ./.venv/bin/python3 -m robertos einrichten"
echo "Danach den Zeitplan aktivieren:"
echo "  bash scripts/install_cron.sh"
