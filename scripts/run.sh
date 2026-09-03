#!/usr/bin/env bash
# Startet einen Robert-OS Befehl und schreibt alles mit.
# Wird vom Zeitplan (cron) aufgerufen.
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
mkdir -p logs

PYTHON="$PROJECT_DIR/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"

LOGFILE="logs/robertos-$(date +%Y-%m).log"
{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') | robertos $* ====="
  "$PYTHON" -m robertos "$@" 2>&1
  echo "----- Ende (Rueckgabewert $?) -----"
} >> "$LOGFILE"
