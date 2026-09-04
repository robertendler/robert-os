#!/usr/bin/env bash
# Vergibt der Oracle-Maschine "robert-os" eine oeffentliche IP-Adresse.
#
# Gedacht fuer die Oracle Cloud Shell. Dort hochladen und starten mit:
#   bash ip.sh
#
# Der Weg ueber die Klick-Oberflaeche scheitert auf dem Handy daran, dass
# der Schalter "Automatically assign public IPv4 address" grau bleibt,
# obwohl das Subnetz oeffentlich ist.

set -uo pipefail

NAME="${1:-robert-os}"

echo "=============================================="
echo " Oeffentliche IP-Adresse fuer '$NAME' vergeben"
echo "=============================================="
echo

fehler() { echo; echo "FEHLER: $1"; echo; exit 1; }

# --- Konto ermitteln --------------------------------------------------
KONTO="${OCI_TENANCY:-}"
if [ -z "$KONTO" ] || [ "$KONTO" = "null" ]; then
  KONTO=$(oci iam availability-domain list \
    --query 'data[0]."compartment-id"' --raw-output 2>/dev/null)
fi
[ -n "$KONTO" ] && [ "$KONTO" != "null" ] \
  || fehler "Dein Oracle-Konto konnte nicht ermittelt werden."

# --- 1. Maschine ------------------------------------------------------
echo "1/4  Maschine suchen ..."
INSTANZ=$(oci compute instance list -c "$KONTO" --display-name "$NAME" \
  --lifecycle-state RUNNING --query 'data[0].id' --raw-output 2>/dev/null)
[ -n "$INSTANZ" ] && [ "$INSTANZ" != "null" ] \
  || fehler "Keine laufende Maschine namens '$NAME' gefunden."
echo "     gefunden"

# --- 2. Netzwerkkarte -------------------------------------------------
echo "2/4  Netzwerkkarte suchen ..."
VNIC=$(oci compute instance list-vnics --instance-id "$INSTANZ" \
  --query 'data[0].id' --raw-output 2>/dev/null)
[ -n "$VNIC" ] && [ "$VNIC" != "null" ] \
  || fehler "Die Netzwerkkarte der Maschine wurde nicht gefunden."
echo "     gefunden"

# --- 3. Private Adresse -----------------------------------------------
echo "3/4  Interne Adresse suchen ..."
PRIVAT=$(oci network private-ip list --vnic-id "$VNIC" \
  --query 'data[0].id' --raw-output 2>/dev/null)
[ -n "$PRIVAT" ] && [ "$PRIVAT" != "null" ] \
  || fehler "Die interne Adresse der Maschine wurde nicht gefunden."
echo "     gefunden"

# --- 4. Oeffentliche Adresse ------------------------------------------
VORHANDEN=$(oci compute instance list-vnics --instance-id "$INSTANZ" \
  --query 'data[0]."public-ip"' --raw-output 2>/dev/null)
if [ -n "$VORHANDEN" ] && [ "$VORHANDEN" != "null" ]; then
  echo
  echo "Es gibt bereits eine oeffentliche Adresse. Nichts zu tun."
  echo
  echo "   DEINE IP-ADRESSE:  $VORHANDEN"
  echo
  exit 0
fi

echo "4/4  Oeffentliche Adresse anlegen ..."
AUSGABE=$(oci network public-ip create -c "$KONTO" --lifetime EPHEMERAL \
  --private-ip-id "$PRIVAT" --query 'data."ip-address"' --raw-output 2>&1)
ERGEBNIS=$?

if [ $ERGEBNIS -ne 0 ] || [ -z "$AUSGABE" ] || [ "$AUSGABE" = "null" ]; then
  echo
  echo "Das Anlegen ist fehlgeschlagen. Meldung von Oracle:"
  echo "$AUSGABE"
  echo
  echo "Schick diese Meldung weiter, dann wird sie ausgewertet."
  exit 1
fi

echo
echo "=============================================="
echo "   FERTIG"
echo
echo "   DEINE IP-ADRESSE:  $AUSGABE"
echo
echo "   In Termius als 'Hostname' eintragen."
echo "   Benutzername: opc"
echo "=============================================="
