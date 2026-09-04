#!/usr/bin/env bash
# Legt eine Sicherungskopie der Datenbank an. Laeuft im laufenden Betrieb.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
sqlite3 data/robertos.db ".backup 'backups/robertos-$STAMP.db'"
ls -1t backups/*.db | tail -n +15 | xargs -r rm --
echo "Sicherung erstellt: backups/robertos-$STAMP.db"
