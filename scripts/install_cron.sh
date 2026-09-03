#!/usr/bin/env bash
# Traegt den Robert-OS Zeitplan in den Zeitplaner des Servers ein.
# Bestehende Eintraege von Robert-OS werden vorher entfernt, damit
# nichts doppelt laeuft.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKER_START="# >>> robert-os >>>"
MARKER_END="# <<< robert-os <<<"

BLOCK=$(sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$PROJECT_DIR/scripts/crontab.txt")

CURRENT=$(crontab -l 2>/dev/null || true)
CLEANED=$(printf '%s\n' "$CURRENT" | sed "/$MARKER_START/,/$MARKER_END/d")

{
  printf '%s\n' "$CLEANED" | sed '/^$/d'
  echo "$MARKER_START"
  echo "$BLOCK"
  echo "$MARKER_END"
} | crontab -

echo "Zeitplan eingetragen. Aktuell aktiv:"
crontab -l | sed -n "/$MARKER_START/,/$MARKER_END/p"
