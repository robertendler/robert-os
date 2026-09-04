# Robert-OS

Ein System aus vier Agenten, das rund um die Uhr auf einem eigenen Server
laeuft, sich per Telegram meldet und seine Daten in einer echten Datenbank
haelt.

Die vier Agenten:

| Agent | Wofuer zustaendig |
|---|---|
| Robert-OS Main | Tagessteuerung, Prioritaeten, Nachhalten |
| Sales Main | Kontakte, Angebote, Nachfassen, Abschluesse |
| Performance Main | Schlaf, Bewegung, Energie, Konzentration |
| Reality Check Main | Deckt Luecken zwischen Behauptung und Datenlage auf |

**Wenn du gerade erst anfaengst: lies [ANLEITUNG.md](ANLEITUNG.md).**
Dort steht jeder Schritt einzeln erklaert, ohne Fachbegriffe.

## Warum das anders ist als das alte System

| Problem frueher | Loesung hier |
|---|---|
| Google Sheets ohne Transaktionen, Agenten ueberschrieben sich | SQLite mit echtem `BEGIN` / `COMMIT` / `ROLLBACK` |
| Zeilennummern als Identitaet, Zeilen wurden geraten | Jede Zeile hat eine feste, unveraenderliche `id` |
| Kein Locking, gleichzeitige Schreibzugriffe kollidierten | `BEGIN IMMEDIATE` serialisiert Schreiber, durch Test belegt |
| "Gespeichert" gemeldet, obwohl der Write fehlschlug | Telegram-Meldung geht erst nach erfolgreichem `COMMIT` raus |
| ChatGPT-Automationen ohne verlaessliche Push-Nachricht | Echter `cron`-Zeitplan plus Telegram-Bot |

## Befehle

Alle Befehle im Projektordner ausfuehren:

```bash
python3 -m robertos einrichten      # Zugangsdaten abfragen (ohne Texteditor)
python3 -m robertos init            # Datenbank anlegen
python3 -m robertos doctor          # Alles durchpruefen
python3 -m robertos chat-id         # Telegram-Chat-ID herausfinden
python3 -m robertos test-telegram   # Testnachricht aufs Handy
python3 -m robertos test-api        # Verbindung zur KI testen
python3 -m robertos status          # Aktuellen Stand anzeigen
python3 -m robertos jobs            # Alle geplanten Laeufe auflisten
python3 -m robertos job abend       # Einen Lauf sofort starten
python3 -m robertos agent sales_main
python3 -m robertos note "Meier hat zugesagt"
python3 -m robertos poll            # Telegram-Nachrichten abholen
```

## Zeitplan

| Wann | Lauf | Agenten |
|---|---|---|
| taeglich 07:20 | `morgen` | Performance Main, Robert-OS Main |
| taeglich 11:30 und 16:30 | `accountability` | Robert-OS Main |
| taeglich 21:00 | `abend` | Sales, Performance, Robert-OS Main |
| sonntags 19:00 | `woche` | alle vier |
| alle 5 Minuten | `poll` | keine KI, nur Telegram abholen |
| optional stuendlich | `orchestrierung` | Reality Check, Robert-OS Main |

## Aufbau des Projekts

```
robertos/          Das Programm
  config.py        Liest die Zugangsdaten aus .env
  db.py            Datenbank mit Transaktionen
  schema.sql       Die Tabellenstruktur
  llm.py           Anbindung an die KI von Anthropic
  telegram.py      Nachrichten aufs Handy
  agents.py        Der Ablauf eines Agentenlaufs
  jobs.py          Die geplanten Laeufe
  cli.py           Bedienung ueber die Kommandozeile
prompts/           Die Rollentexte der vier Agenten (frei editierbar)
scripts/           Einrichtung des Servers und Zeitplan
tests/             Automatische Tests
data/              Die Datenbank (wird nicht ins Internet geladen)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Kosten

Server bei Oracle Cloud im Always-Free-Tier: dauerhaft kostenlos.
Telegram: kostenlos. Die KI wird nur zu den geplanten Zeitpunkten
aufgerufen, nicht dauerhaft. Jeder Lauf schreibt seine geschaetzten
Kosten ins Protokoll, sichtbar in `logs/`.
