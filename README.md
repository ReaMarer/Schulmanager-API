# Schulmanager-API-2

Automatisierte Hausaufgaben-Synchronisation fuer **Schulmanager Online** und
Obsidian:

1. `scraper.py` meldet sich per Playwright an, liest die Hausaufgaben aus der
   Schulmanager-Ansicht und speichert sie in `hausaufgaben.db` (SQLite).
2. `markdown_export.py` liest die Hausaufgaben des aktuellen Tages aus der
   Datenbank und ergaenzt fehlende Eintraege in der Tagesnotiz des Obsidian-
   Vaults. Die Notiz wird per Nextcloud-WebDAV gelesen und geschrieben.

Beide Schritte laufen stuendlich ueber `run_hourly.sh` und einen Cronjob.

## Verhalten des Markdown-Exports

- Massgeblich ist das Datum in der Zeitzone `Europe/Berlin`, nicht die
  Server-Zeitzone.
- Der Exporter vergleicht die **Identitaet** jeder Aufgabe (Fach + Inhalt,
  ohne Status- und Datums-Emojis) mit den bereits vorhandenen Checkboxen.
- Nur fehlende Aufgaben werden am Ende der Notiz angehaengt. Vorhandene
  Zeilen werden weder ersetzt noch umsortiert.
- `last_updated` im Frontmatter wird nur aktualisiert, wenn tatsaechlich etwas
  hinzukommt.
- Mehrzeilige Hausaufgaben werden wie bisher in eine Checkbox pro Zeile
  aufgeteilt.
- Das Faelligkeitsdatum (`📅`) wird aus `stundenplan.json` berechnet: naechster
  Schultag, an dem das Fach auf dem Plan steht (Wochenenden werden
  uebersprungen).
- Nach erfolgreichem Schreiben werden die betroffenen Datenbankzeilen auf
  `synchronisiert = 1` gesetzt.

Beispiel einer Tagesnotiz:

```markdown
---
date: 2026-10-14
last_updated: 2026-10-14 23:00:07
tags:
  - schule
  - hausaufgaben
---
# 📚 Hausaufgaben für Mittwoch, 14.10.2026
- [ ] **PRAKTISCHE PHIL.**: Keine HA 📅 2026-10-20 ➕ 2026-10-14 ⏫
- [ ] **Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫
```

## Voraussetzungen

- Linux (getestet auf Ubuntu-Server und Arch/CachyOS)
- Python 3.10+
- Internetzugang und gueltige Schulmanager-Zugangsdaten
- Nextcloud mit WebDAV-Zugriff auf den Obsidian-Vault

## Installation

```bash
cd /home/marlon/Schulmanager-API-2

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Auf schlanken Linux-Systemen kann Chromium zusaetzliche Systembibliotheken
benoetigen. Falls der Browser mit fehlenden `.so`-Dateien abbricht, installiere
die von Playwright benoetigten Pakete (auf Arch z. B. `nss`, `atk`, `cups`,
`gtk3`, `libdrm`, `libxkbcommon`, `alsa-lib`) oder fuehre
`playwright install-deps chromium` auf einer Distribution mit Unterstuetzung
dafuer aus.

## Konfiguration

Zugangsdaten gehoeren **nicht** ins Repository. Lege eine lokale `.env` mit
Modus `0600` an:

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
```

```dotenv
SCHULMANAGER_EMAIL=deine.email@example.com
SCHULMANAGER_PASSWORD=dein-passwort
SCHULMANAGER_HEADLESS=true

NEXTCLOUD_DAV_BASE=http://127.0.0.1:8080/remote.php/dav/files/marlon/orga_vault/00%20Meta/Hausaufgaben
NEXTCLOUD_USER=marlon
NEXTCLOUD_PASSWORD=dein-nextcloud-passwort
```

Unterstuetzte Umgebungsvariablen:

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `SCHULMANAGER_EMAIL` | E-Mail/Benutzername | – |
| `SCHULMANAGER_USERNAME`, `SCHULMANAGER_USER` | Alternativen zu `SCHULMANAGER_EMAIL` | – |
| `SCHULMANAGER_PASSWORD` | Passwort | – |
| `SCHULMANAGER_DB` | Pfad zur SQLite-Datei | `hausaufgaben.db` |
| `SCHULMANAGER_HEADLESS` | `false`/`0` fuer sichtbaren Browser | `true` |
| `SCHULMANAGER_STUNDENPLAN` | Pfad zum Stundenplan | `stundenplan.json` |
| `NEXTCLOUD_DAV_BASE` | WebDAV-URL des Hausaufgaben-Ordners | – |
| `NEXTCLOUD_USER` | Nextcloud-Benutzername | – |
| `NEXTCLOUD_PASSWORD` | Nextcloud-Passwort/App-Passwort | – |

Auf dem Server zeigt `NEXTCLOUD_DAV_BASE` auf `127.0.0.1:8080`; aus dem LAN ist
die Nextcloud unter `http://100.71.43.93:8080` erreichbar.

## Verwendung

### Scraper

```bash
# Normaler Lauf: einloggen, scrapen, in SQLite synchronisieren
.venv/bin/python scraper.py

# Nur anzeigen, nichts in die Datenbank schreiben
.venv/bin/python scraper.py --dry-run

# Sichtbarer Browser zum Debuggen
.venv/bin/python scraper.py --no-headless

# Roh-HTML fuer Fehlersuche speichern
.venv/bin/python scraper.py --dump-html debug/homework.html

# Bereits gespeichertes HTML offline parsen (ohne Login)
.venv/bin/python scraper.py --input-html debug/homework.html --dry-run
```

### Markdown-Export

```bash
# Heutige fehlende Eintraege per WebDAV anhaengen
.venv/bin/python markdown_export.py

# Nur anzeigen, was angehaengt wuerde
.venv/bin/python markdown_export.py --dry-run

# Gegen ein lokales Verzeichnis statt WebDAV schreiben (Tests/Backfill)
.venv/bin/python markdown_export.py --date 2026-10-14 --note-dir ./notes

# Abweichende Datenbank oder Stundenplan verwenden
.venv/bin/python markdown_export.py --db andere.db --stundenplan plan.json
```

Wichtige Optionen des Exporters:

```text
--db PFAD                 SQLite-Datenbank
--stundenplan PFAD        Stundenplan (JSON)
--date YYYY-MM-DD         Zieldatum statt heute (Europe/Berlin)
--note-dir PFAD           Lokales Notizverzeichnis statt WebDAV
--dav-base URL            WebDAV-Basis-URL
--dav-user USER           Nextcloud-Benutzer
--dav-password PASSWORT   Nextcloud-Passwort (besser: .env)
--dry-run                 Nichts schreiben
-v, --verbose             Debug-Logging
```

## Automatisierung per Cron

`run_hourly.sh` startet zuerst den Scraper und danach den Markdown-Export. Der
Export laeuft auch dann, wenn der Scraper fehlschlaegt, damit bereits
vorhandene Datenbankeintraege trotzdem in die Notiz gelangen. Ein `flock`
verhindert parallele Laeufe.

Crontab des Benutzers `marlon`:

```cron
0 * * * * /bin/bash /home/marlon/Schulmanager-API-2/run_hourly.sh >> /home/marlon/Schulmanager-API-2/cron.log 2>&1
```

Installation:

```bash
crontab -e
# obige Zeile einfuegen und speichern
```

Der frueher benutzte Root-Cronjob
(`/home/marlon/Schulmanager-API/run.sh`) ist deaktiviert. Der neue Job laeuft
bewusst als Benutzer `marlon`, damit WebDAV-Zugangsdaten und Projektdateien
nicht als Root verarbeitet werden.

Logs pruefen:

```bash
tail -f /home/marlon/Schulmanager-API-2/cron.log
```

## Datenbankschema

Die Tabelle wird beim ersten Lauf automatisch angelegt:

```sql
CREATE TABLE IF NOT EXISTS homework (
    id TEXT PRIMARY KEY,
    datum TEXT,
    fach TEXT,
    inhalt TEXT,
    synchronisiert INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- `id`: MD5 aus `fach`, `datum` und `inhalt`
- `datum`: Schulmanager-Datum, z. B. `Montag, 02.11.2026`
- `synchronisiert`: `0` = noch nicht in die Notiz uebernommen,
  `1` = erfolgreich uebernommen
- `created_at`: Zeitpunkt des Einfuegens

Beispielabfrage:

```bash
sqlite3 hausaufgaben.db \
  "SELECT datum, fach, inhalt FROM homework WHERE synchronisiert = 0 ORDER BY datum;"
```

## Tests

Die Tests benoetigen keinen Login und keine Netzwerkverbindung. Sie pruefen
Parser, ID-Berechnung, Datenbank-Synchronisation, Faelligkeitsberechnung und
das append-only Zusammenfuehren der Markdown-Notiz:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Projektstruktur

```text
.
├── scraper.py                  # CLI, Parser, Datenbank, Playwright-Logik
├── markdown_export.py          # Append-only Markdown-Export (WebDAV/lokal)
├── stundenplan.json            # Stundenplan fuer Faelligkeitsdaten
├── run_hourly.sh               # Cron-Wrapper: Scraper + Export, flock
├── requirements.txt            # Laufzeitabhaengigkeiten
├── requirements-dev.txt        # zusaetzlich pytest
├── .env.example                # Vorlage fuer Zugangsdaten
├── tests/
│   ├── test_parser_and_db.py
│   ├── test_multiline.py
│   └── test_markdown_export.py
├── pytest.ini
└── README.md
```

## Fehlerbehebung

| Problem | Loesung |
| --- | --- |
| `Executable doesn't exist` | `playwright install chromium` im aktivierten `.venv` ausfuehren |
| Login schlaegt fehl | Zugangsdaten in `.env` pruefen; ggf. `--no-headless` und `--dump-html` nutzen |
| Keine Kacheln gefunden | Moeglicherweise keine Hausaufgaben vorhanden; mit `--dump-html` das HTML pruefen |
| WebDAV `HTTP 401` | `NEXTCLOUD_USER`/`NEXTCLOUD_PASSWORD` pruefen |
| WebDAV `HTTP 404` | `NEXTCLOUD_DAV_BASE` pruefen; der Ordner muss existieren |
| Falsches Faelligkeitsdatum | `stundenplan.json` und Fachnamen pruefen |
| Datenbank gesperrt | Parallelen Lauf beenden; `flock` im Cron-Wrapper pruefen |
| Falsches Schuljahr/Modul | URL bzw. Schulmanager-Berechtigungen pruefen |

## Hinweise

- Die DOM-Selektoren (`div.tile`, `div.tile-header`, `div.tile-body`, `h4`,
  `p.homework-paragraph`) folgen der aktuellen Schulmanager-Ansicht. Aendert
  Schulmanager das Markup, muss `parse_homework` angepasst werden.
- Das Skript speichert keine Passwoerter; es liest sie nur aus Umgebung/CLI.
- `--password` bzw. `--dav-password` auf der Kommandozeile ist weniger sicher
  als `.env`, weil es in der Prozessliste sichtbar sein kann.
- Der Scraper ist fuer den persoenlichen Gebrauch mit eigenen Zugangsdaten
  gedacht. Beachte die Nutzungsbedingungen von Schulmanager Online.
