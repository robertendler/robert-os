# Robert-OS einrichten - Schritt fuer Schritt

Diese Anleitung ist fuer dich geschrieben, nicht fuer Programmierer.
Arbeite sie von oben nach unten ab. Jeder Schritt sagt dir, was du tust
und warum. Mach nach jedem Schritt eine Pause, wenn du willst - nichts
davon laeuft weg.

Was am Ende dabei herauskommt: Ein kleiner Computer im Internet, der dir
morgens, mittags, nachmittags und abends von selbst auf dein Handy
schreibt und mitschreibt, was du zusagst und was du tust.

---

## Schritt 1: Ein Server bei Oracle Cloud

**Was ist das?** Ein Computer, der im Internet steht und nie ausgeht.
Deiner zu Hause faellt aus, wenn du ihn zuklappst. Dieser hier nicht.
Oracle verschenkt so einen Computer dauerhaft ("Always Free"), nicht als
Testphase.

**Was du tust:**

1. Geh auf `cloud.oracle.com` und klick auf "Start for free".
2. Land: Germany. E-Mail-Adresse eingeben, bestaetigen.
3. Du wirst nach einer Kreditkarte gefragt. Das ist nur zur Pruefung,
   dass du ein Mensch bist. Solange du im Free-Tier bleibst, wird nichts
   abgebucht. Es werden kurzzeitig etwa 1 Euro reserviert und wieder
   freigegeben.
4. Nach der Anmeldung im Menue links auf "Compute" und dann "Instances".
5. "Create Instance" klicken.
6. Wichtig bei der Auswahl: Bei "Image and shape" muss **"Always Free
   eligible"** stehen. Nimm als Betriebssystem **Ubuntu**.
7. Bei "Add SSH keys" waehl "Generate a key pair for me" und lade
   **beide** Dateien herunter. Die Datei mit der Endung `.key` ist dein
   Schluessel zu diesem Computer. Verlier sie nicht.
8. "Create" klicken. Nach ein bis zwei Minuten steht dort eine
   "Public IP address", zum Beispiel `130.61.12.34`. Notier sie.

**Woran du merkst, dass es geklappt hat:** Die Instanz ist gruen und
zeigt eine oeffentliche IP-Adresse an.

---

## Schritt 2: Auf den Server verbinden

**Was ist das?** Du oeffnest ein Textfenster, in dem du dem Server Befehle
gibst. Es sieht altmodisch aus, ist aber der einfachste Weg.

**Was du tust:**

Am Mac das Programm "Terminal" oeffnen, unter Windows "PowerShell".
Dann eintippen (die IP und den Pfad zur Schluesseldatei anpassen):

```bash
chmod 600 ~/Downloads/ssh-key-2026.key
ssh -i ~/Downloads/ssh-key-2026.key ubuntu@130.61.12.34
```

Beim ersten Mal fragt er "Are you sure you want to continue connecting?".
Tipp `yes` und Enter.

**Woran du merkst, dass es geklappt hat:** Die Zeile beginnt jetzt mit
`ubuntu@` statt mit deinem Namen.

---

## Schritt 3: Robert-OS auf den Server holen

**Was ist das?** Das Programm, das ich gebaut habe, wird auf den Server
kopiert und dort eingerichtet.

**Was du tust:** Diese drei Zeilen nacheinander eintippen:

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone -b claude/robert-os-setup-gol0im https://github.com/robertendler/robert-os.git
cd robert-os && bash scripts/setup_server.sh
```

Der Zusatz `-b claude/robert-os-setup-gol0im` holt die aktuelle Fassung.
Sobald du sie auf GitHub in die Hauptversion uebernommen hast, kannst du
den Zusatz weglassen.

Das Einrichtungsskript macht sechs Dinge: Systempakete installieren,
Zeitzone auf Berlin stellen, eine abgeschottete Python-Umgebung anlegen,
die Datei fuer deine Zugangsdaten vorbereiten, die Datenbank anlegen und
einen Selbsttest fahren.

Am Ende meldet der Selbsttest, dass der API-Key und der Telegram-Token
noch fehlen. Das ist richtig so - die holen wir jetzt.

---

## Schritt 4: Der Telegram-Bot

**Was ist das?** Ein kostenloser Absender, der dir echte Push-Nachrichten
aufs Handy schickt. Genau das, was bei den ChatGPT-Automationen nie
zuverlaessig funktioniert hat.

**Was du tust:**

1. Telegram auf dem Handy oeffnen, oben in die Suche `BotFather` eingeben
   und den Kontakt mit dem blauen Haken oeffnen.
2. `/newbot` schicken.
3. Er fragt nach einem Namen. Nimm zum Beispiel `Robert OS`.
4. Er fragt nach einem Benutzernamen. Der muss auf `bot` enden, zum
   Beispiel `robert_os_2026_bot`.
5. Er antwortet mit einer langen Zeichenkette wie
   `8123456789:AAHxyz...`. Das ist dein Token. Behandle ihn wie ein
   Passwort.
6. Schick deinem neuen Bot in Telegram einmal irgendeine Nachricht,
   zum Beispiel `hallo`. Ohne das kann er dir nicht antworten.

---

## Schritt 5: Der Anthropic API-Key

**Was ist das?** Der Zugang zur KI. Der Server kann sich nicht in einen
Chat einloggen, deshalb braucht er einen eigenen Schluessel. Abgerechnet
wird nach Nutzung, nicht pauschal.

**Was du tust:**

1. Geh auf `console.anthropic.com` und melde dich an.
2. Unter "Billing" eine Zahlungsmethode hinterlegen und einen kleinen
   Betrag aufladen, zum Beispiel 10 Dollar. Das reicht bei diesem
   Zeitplan lange.
3. Links auf "API Keys", dann "Create Key". Name egal, zum Beispiel
   `robert-os`.
4. Der Schluessel beginnt mit `sk-ant-`. **Er wird nur einmal angezeigt.**
   Kopier ihn sofort.
5. Optional, aber empfohlen: Unter "Limits" ein monatliches Ausgabenlimit
   setzen, damit nie mehr abgebucht werden kann als du willst.

---

## Schritt 6: Zugangsdaten eintragen

**Was ist das?** Die drei Werte aus Schritt 4 und 5 kommen in eine Datei
auf dem Server. Diese Datei verlaesst den Server nie und wird nicht ins
Internet geladen.

**Was du tust:** Auf dem Server (im Fenster aus Schritt 2):

```bash
cd ~/robert-os
nano .env
```

Es oeffnet sich ein einfacher Texteditor. Trag hinter das Gleichheitszeichen
deine Werte ein, ohne Anfuehrungszeichen und ohne Leerzeichen:

```
ANTHROPIC_API_KEY=sk-ant-hier-dein-key
TELEGRAM_BOT_TOKEN=8123456789:AAHhier-dein-token
TELEGRAM_CHAT_ID=
```

Die Chat-ID laesst du erst mal leer. Speichern mit `Strg+O`, dann Enter,
dann `Strg+X` zum Schliessen.

Jetzt die Chat-ID herausfinden:

```bash
./.venv/bin/python3 -m robertos chat-id
```

Der Befehl zeigt dir eine Zahl an, zum Beispiel `123456789`. Trag sie mit
`nano .env` bei `TELEGRAM_CHAT_ID` ein und speichere wieder.

Falls nichts angezeigt wird: Schick deinem Bot in Telegram noch einmal
eine Nachricht und fuehr den Befehl erneut aus.

---

## Schritt 7: Alles pruefen

```bash
./.venv/bin/python3 -m robertos doctor
./.venv/bin/python3 -m robertos test-telegram
./.venv/bin/python3 -m robertos test-api
```

Der erste Befehl geht die Liste durch und sagt dir bei jedem Punkt "OK"
oder was fehlt. Der zweite schickt dir eine Testnachricht aufs Handy.
Der dritte stellt der KI eine Testfrage und zeigt dir, was der Aufruf
gekostet hat.

**Erst weitermachen, wenn alle drei durchlaufen.**

---

## Schritt 8: Den Zeitplan einschalten

**Was ist das?** Ab jetzt startet der Server die Laeufe von selbst, auch
wenn du dein Fenster schliesst und dein Rechner aus ist.

```bash
bash scripts/install_cron.sh
```

Danach laeuft automatisch:

| Wann | Was passiert |
|---|---|
| taeglich 07:20 | Tag planen, drei Prioritaeten setzen |
| taeglich 11:30 | Nachhaken, was vom Plan noch fehlt |
| taeglich 16:30 | Noch einmal nachhaken |
| taeglich 21:00 | Tag abschliessen, Offenes auf morgen ziehen |
| sonntags 19:00 | Woche auswerten, Faktencheck |
| alle 5 Minuten | Deine Telegram-Nachrichten einsammeln (kostet nichts) |

Zum Ausprobieren, ohne auf die Uhrzeit zu warten:

```bash
./.venv/bin/python3 -m robertos job abend
```

---

## Schritt 9: Die Agenten auf dich zuschneiden

Im Ordner `prompts` liegen fuenf Textdateien. Sie bestimmen, wie die
Agenten sich verhalten. Das ist normaler Text, kein Programmcode - du
kannst dort alles aendern.

- `_gemeinsame_regeln.md` gilt fuer alle vier
- `robert_os_main.md`, `sales_main.md`, `performance_main.md` und
  `reality_check_main.md` je fuer einen Agenten

In jeder der vier Rollendateien steht unten ein Platzhalter. Dort gehoert
der Inhalt deiner bisherigen vier Configs hin. Bearbeiten mit:

```bash
nano prompts/sales_main.md
```

Aenderungen wirken sofort beim naechsten Lauf. Ein Neustart ist nicht
noetig.

---

## Der taegliche Umgang

**Dem System etwas sagen:** Schreib deinem Telegram-Bot einfach eine
Nachricht. Sie wird innerhalb von fuenf Minuten eingesammelt und der
naechste Agentenlauf sieht sie.

**Nachschauen, was das System weiss:**

```bash
./.venv/bin/python3 -m robertos status
```

**Sehen, was gelaufen ist:**

```bash
tail -50 logs/robertos-*.log
```

**Sicherung der Daten anlegen:**

```bash
bash scripts/backup.sh
```

---

## Wenn etwas nicht funktioniert

| Symptom | Ursache und Loesung |
|---|---|
| Keine Nachrichten mehr aufs Handy | `robertos doctor` ausfuehren. Meist ist das Guthaben bei Anthropic leer. |
| "Fehlende Angabe" beim Start | In `.env` fehlt ein Wert. `nano .env` und nachtragen. |
| `chat-id` findet nichts | Dem Bot in Telegram eine Nachricht schicken, dann erneut versuchen. |
| Der Zeitplan laeuft nicht | `crontab -l` zeigt die Eintraege. Fehlen sie, `bash scripts/install_cron.sh` nochmal ausfuehren. |
| Ein Lauf ist fehlgeschlagen | In `logs/` steht der genaue Grund. Fehler werden immer mitgeschrieben, nie verschwiegen. |

---

## Was das System bewusst NICHT tut

- Es behauptet nie, etwas gespeichert zu haben, wenn das Speichern
  fehlschlug. Die Meldung aufs Handy geht erst raus, nachdem die
  Datenbank die Aenderung bestaetigt hat.
- Es hakt keine Aufgabe ab, die einem anderen Agenten gehoert.
- Es schickt keine leeren Statusmeldungen. Wenn nichts passiert ist,
  kommt keine Nachricht.
