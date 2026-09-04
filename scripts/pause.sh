#!/usr/bin/env bash
# Legt Robert-OS still: keine geplanten Laeufe, kein antwortender Bot,
# also keine Kosten mehr. Daten und Einstellungen bleiben unberuehrt.
#
# Rueckgaengig machen mit:
#   bash scripts/install_cron.sh && bash scripts/install_bot.sh
set -uo pipefail

MARKER_START="# >>> robert-os >>>"
MARKER_END="# <<< robert-os <<<"

echo "== Robert-OS stilllegen =="

if systemctl list-unit-files 2>/dev/null | grep -q robert-os-bot; then
  sudo systemctl disable --now robert-os-bot 2>/dev/null \
    && echo "  Gespraechsdienst gestoppt und vom Autostart genommen." \
    || echo "  Gespraechsdienst liess sich nicht stoppen, bitte pruefen."
else
  echo "  Gespraechsdienst war nicht eingerichtet."
fi

if crontab -l >/dev/null 2>&1; then
  if crontab -l | grep -q "$MARKER_START"; then
    crontab -l | sed "/$MARKER_START/,/$MARKER_END/d" | crontab -
    echo "  Zeitplan entfernt. Es laeuft nichts mehr von selbst."
  else
    echo "  Kein Robert-OS Zeitplan gefunden."
  fi
else
  echo "  Kein Zeitplan vorhanden."
fi

echo
echo "Ab jetzt entstehen keine Kosten mehr."
echo "Datenbank, Zugangsdaten und Rollentexte bleiben erhalten."
echo
echo "Zur Kontrolle:"
echo "  crontab -l                              (sollte leer sein)"
echo "  systemctl is-active robert-os-bot       (sollte inactive sein)"
