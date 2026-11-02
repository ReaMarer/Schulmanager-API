#!/usr/bin/env python3
"""Hausaufgaben aus SQLite append-only in die taegliche Obsidian-Notiz schreiben.

Der Exporter liest die Hausaufgaben des aktuellen Tages (Zeitzone
``Europe/Berlin``) aus der SQLite-Datenbank, vergleicht sie mit der bereits
vorhandenen Markdown-Notiz und haengt nur fehlende Eintraege an. Vorhandene
Zeilen werden nicht neu geschrieben oder umsortiert; lediglich
``last_updated`` wird aktualisiert, wenn tatsaechlich etwas hinzukommt.

Die Notiz wird standardmaessig per Nextcloud-WebDAV gelesen und geschrieben.
Fuer Tests oder einen manuellen Lauf gegen ein lokales Verzeichnis gibt es
``--note-dir``.

Beispiel:
    .venv/bin/python markdown_export.py
    .venv/bin/python markdown_export.py --dry-run
    .venv/bin/python markdown_export.py --date 2026-10-14 --note-dir ./notes
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

__version__ = "1.0.0"

LOGGER = logging.getLogger("markdown_export")

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path("hausaufgaben.db")
DEFAULT_STUNDENPLAN_PATH = PROJECT_DIR / "stundenplan.json"
BERLIN = ZoneInfo("Europe/Berlin")

GERMAN_WEEKDAYS = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)

SUBJECT_MAPPING = {
    "PRAKTISCHE PHIL.": "Praktische Philosophie",
    "Mathematik": "Mathematik",
    "Englisch": "Englisch",
    "Deutsch": "Deutsch",
    "Chemie": "Chemie",
    "Erdkunde": "Erdkunde",
    "Sport": "Sport",
    "Physik": "Physik",
    "Informatik": "Informatik",
    "Geschichte": "Geschichte",
    "Biologie": "Biologie",
    "Lateinisch, regulärer Beginn in Jahrgang 7": "Latein",
}

# Task-Metadaten beginnen mit einem dieser Emojis. Alles davor ist die
# stabile Identitaet der Aufgabe, unabhaengig von Status und Datumswerten.
METADATA_EMOJIS = ("📅", "➕", "⏫", "🔽", "⏳", "✅", "❌", "🛫", "⏬", "🔁")
METADATA_RE = re.compile(r"\s*(?:" + "|".join(re.escape(e) for e in METADATA_EMOJIS) + ")")
CHECKBOX_RE = re.compile(r"^- \[[ xX]\]\s+(.*)$")
HEADER_RE = re.compile(r"(?m)^#\s*📚\s*Hausaufgaben")
LAST_UPDATED_RE = re.compile(r"(?m)^last_updated:.*$")
DATE_DE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


class ExportError(RuntimeError):
    """Fehler, der dem Benutzer verstaendlich angezeigt werden kann."""


class NoteConflict(ExportError):
    """Die Notiz wurde waehrend des Schreibens von anderer Stelle geaendert."""


class WebDavError(ExportError):
    """Nextcloud-WebDAV konnte nicht gelesen oder geschrieben werden."""


@dataclass(frozen=True)
class HomeworkRecord:
    """Eine bereits auf den Zieldatum gefilterte Hausaufgabe."""

    id: str
    fach: str
    inhalt: str


@dataclass(frozen=True)
class ExportEntry:
    """Eine einzelne Checkbox-Zeile samt ihrer Vergleichs-Identitaet."""

    identity: str
    line: str


@dataclass(frozen=True)
class NoteUpdate:
    """Ergebnis des Zusammenfuehrens von Notiz und Datenbank."""

    content: str
    appended: tuple[ExportEntry, ...]
    created: bool


# ---------------------------------------------------------------------------
# Datum und Stundenplan
# ---------------------------------------------------------------------------


def parse_homework_date(value: str) -> date | None:
    """Lies ein Datum aus ``Montag, 03.11.2026`` oder ``2026-11-03``."""

    match = DATE_DE_RE.search(value)
    if match:
        day, month, year = (int(part) for part in match.groups())
    else:
        match = DATE_ISO_RE.search(value)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())

    try:
        return date(year, month, day)
    except ValueError:
        return None


def load_timetable(path: str | Path = DEFAULT_STUNDENPLAN_PATH) -> dict[str, list[str]]:
    """Lade den Stundenplan; bei Fehlern wird mit leerem Plan weitergemacht."""

    timetable_path = Path(path).expanduser()
    if not timetable_path.exists():
        LOGGER.warning("Stundenplan nicht gefunden: %s", timetable_path)
        return {}

    try:
        import json

        data = json.loads(timetable_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOGGER.warning("Stundenplan konnte nicht gelesen werden (%s): %s", timetable_path, exc)
        return {}

    if not isinstance(data, dict):
        LOGGER.warning("Stundenplan hat ein unerwartetes Format: %s", timetable_path)
        return {}

    return {
        str(day): [str(subject) for subject in subjects]
        for day, subjects in data.items()
        if isinstance(subjects, list)
    }


def next_lesson_date(
    current_date: date,
    subject: str,
    timetable: Mapping[str, Sequence[str]],
) -> date:
    """Finde den naechsten Schultag, an dem das Fach auf dem Plan steht.

    Entspricht der bisherigen Logik: fruehestens morgen, Wochenenden werden
    uebersprungen. Wird das Fach nicht gefunden, wird morgen verwendet.
    """

    mapped_subject = SUBJECT_MAPPING.get(subject, subject)
    for offset in range(1, 22):
        candidate = current_date + timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        subjects = timetable.get(GERMAN_WEEKDAYS[candidate.weekday()], [])
        if mapped_subject in subjects:
            return candidate
    return current_date + timedelta(days=1)


def format_note_title(target_date: date) -> str:
    return f"{GERMAN_WEEKDAYS[target_date.weekday()]}, {target_date.strftime('%d.%m.%Y')}"


# ---------------------------------------------------------------------------
# Markdown-Zusammenfuehrung
# ---------------------------------------------------------------------------


def entry_identity(text: str) -> str:
    """Normalisiere eine Aufgabenzeile fuer den Vergleich mit der Notiz."""

    without_metadata = METADATA_RE.split(text.strip(), maxsplit=1)[0]
    return " ".join(without_metadata.split())


def parse_existing_identities(note: str) -> set[str]:
    """Sammle die Identitaeten aller bereits vorhandenen Checkboxen."""

    identities: set[str] = set()
    for line in note.splitlines():
        match = CHECKBOX_RE.match(line.strip())
        if match:
            identity = entry_identity(match.group(1))
            if identity:
                identities.add(identity)
    return identities


def build_entries(
    records: Sequence[HomeworkRecord],
    target_date: date,
    timetable: Mapping[str, Sequence[str]],
) -> list[ExportEntry]:
    """Erzeuge Checkbox-Zeilen aus DB-Datensaetzen.

    Mehrzeilige Hausaufgaben werden wie bisher in eine Zeile pro Aufgabe
    aufgeteilt. Doppelte Identitaeten werden nur einmal ausgegeben.
    """

    entries: list[ExportEntry] = []
    seen: set[str] = set()

    for record in records:
        subject = (record.fach or "").strip()
        content = (record.inhalt or "").strip()

        if not content or "keine ha" in content.lower():
            parts = ["Keine HA"]
        else:
            parts = [line.strip() for line in content.splitlines() if line.strip()]

        due_date = next_lesson_date(target_date, subject, timetable).isoformat()
        for part in parts:
            text = f"**{subject}**: {part}"
            identity = entry_identity(text)
            if identity in seen:
                continue
            seen.add(identity)
            entries.append(
                ExportEntry(
                    identity=identity,
                    line=(
                        f"- [ ] {text} 📅 {due_date} "
                        f"➕ {target_date.isoformat()} ⏫"
                    ),
                )
            )

    return entries


def render_new_note(
    target_date: date,
    entries: Sequence[ExportEntry],
    now: datetime,
) -> str:
    """Erzeuge eine vollstaendige neue Tagesnotiz."""

    lines = [
        "---",
        f"date: {target_date.isoformat()}",
        f"last_updated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "tags:",
        "  - schule",
        "  - hausaufgaben",
        "---",
        f"# 📚 Hausaufgaben für {format_note_title(target_date)}",
    ]
    lines.extend(entry.line for entry in entries)
    return "\n".join(lines) + "\n"


def _update_last_updated(note: str, now: datetime) -> str:
    replacement = f"last_updated: {now.strftime('%Y-%m-%d %H:%M:%S')}"
    return LAST_UPDATED_RE.sub(replacement, note, count=1)


def _unique_entries(entries: Sequence[ExportEntry]) -> list[ExportEntry]:
    unique: list[ExportEntry] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.identity in seen:
            continue
        unique.append(entry)
        seen.add(entry.identity)
    return unique


def build_note(
    existing: str | None,
    target_date: date,
    entries: Sequence[ExportEntry],
    now: datetime,
) -> NoteUpdate:
    """Fuehre bestehende Notiz und DB-Eintraege append-only zusammen."""

    entries = _unique_entries(entries)
    if existing is None or not existing.strip():
        return NoteUpdate(
            content=render_new_note(target_date, entries, now),
            appended=tuple(entries),
            created=True,
        )

    existing_identities = parse_existing_identities(existing)
    missing = [
        entry for entry in entries if entry.identity not in existing_identities
    ]

    if not missing:
        return NoteUpdate(content=existing, appended=(), created=False)

    updated = existing
    if not HEADER_RE.search(updated):
        if not updated.endswith("\n"):
            updated += "\n"
        if not updated.endswith("\n\n"):
            updated += "\n"
        updated += f"# 📚 Hausaufgaben für {format_note_title(target_date)}\n"

    if not updated.endswith("\n"):
        updated += "\n"
    updated += "\n".join(entry.line for entry in missing) + "\n"
    updated = _update_last_updated(updated, now)

    return NoteUpdate(content=updated, appended=tuple(missing), created=False)


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------


def load_homework_for_date(
    db_path: str | Path,
    target_date: date,
) -> list[HomeworkRecord]:
    """Lade alle Hausaufgaben, deren Schulmanager-Datum dem Zieldatum entspricht."""

    path = Path(db_path).expanduser()
    if not path.exists():
        raise ExportError(f"Datenbank nicht gefunden: {path}")

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error as exc:
        raise ExportError(f"Datenbank konnte nicht geoeffnet werden ({path}): {exc}") from exc

    try:
        rows = connection.execute(
            "SELECT id, datum, fach, inhalt FROM homework ORDER BY rowid"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ExportError(f"Datenbank konnte nicht gelesen werden ({path}): {exc}") from exc
    finally:
        connection.close()

    records: list[HomeworkRecord] = []
    for homework_id, datum, fach, inhalt in rows:
        if parse_homework_date(datum or "") != target_date:
            continue
        records.append(
            HomeworkRecord(
                id=str(homework_id),
                fach=str(fach or ""),
                inhalt=str(inhalt or ""),
            )
        )
    return records


def mark_synchronized(db_path: str | Path, homework_ids: Sequence[str]) -> int:
    """Markiere erfolgreich in die Notiz uebernommene Datensaetze."""

    if not homework_ids:
        return 0

    path = Path(db_path).expanduser()
    placeholders = ",".join("?" for _ in homework_ids)
    try:
        with sqlite3.connect(path, timeout=10.0) as connection:
            cursor = connection.execute(
                f"UPDATE homework SET synchronisiert = 1 WHERE id IN ({placeholders})",
                list(homework_ids),
            )
            return cursor.rowcount
    except sqlite3.Error as exc:
        raise ExportError(f"Datenbank konnte nicht aktualisiert werden ({path}): {exc}") from exc


# ---------------------------------------------------------------------------
# Notiz-Speicher (WebDAV / lokal)
# ---------------------------------------------------------------------------


class LocalNoteStore:
    """Lokales Verzeichnis als Notiz-Speicher (Tests/Backfill)."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser()

    def read(self, filename: str) -> tuple[str | None, str | None]:
        path = self.directory / filename
        if not path.exists():
            return None, None
        try:
            return path.read_text(encoding="utf-8"), None
        except OSError as exc:
            raise ExportError(f"Notiz konnte nicht gelesen werden ({path}): {exc}") from exc

    def write(self, filename: str, content: str, etag: str | None = None) -> None:
        path = self.directory / filename
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
        except OSError as exc:
            raise ExportError(f"Notiz konnte nicht geschrieben werden ({path}): {exc}") from exc


class WebDavNoteStore:
    """Nextcloud-WebDAV-Client fuer die Tagesnotizen."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.authorization = f"Basic {token}"

    def _url(self, filename: str) -> str:
        return f"{self.base_url}/{quote(filename, safe='')}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, bytes, Mapping[str, str]]:
        request = urllib.request.Request(url, method=method, data=data)
        request.add_header("Authorization", self.authorization)
        request.add_header("User-Agent", "Schulmanager-API-2")
        for key, value in (headers or {}).items():
            request.add_header(key, value)

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            body = exc.read(500).decode("utf-8", "replace")
            raise WebDavError(f"WebDAV {method} {url} -> HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise WebDavError(f"WebDAV nicht erreichbar ({url}): {exc.reason}") from exc

    def read(self, filename: str) -> tuple[str | None, str | None]:
        url = self._url(filename)
        try:
            status, body, headers = self._request("GET", url)
        except WebDavError as exc:
            if "HTTP 404" in str(exc):
                return None, None
            raise

        if status != 200:
            raise WebDavError(f"WebDAV GET {url} -> unerwarteter Status {status}")
        return body.decode("utf-8"), headers.get("ETag")

    def write(self, filename: str, content: str, etag: str | None = None) -> None:
        headers = {"Content-Type": "text/markdown; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag

        try:
            status, _, _ = self._request(
                "PUT",
                self._url(filename),
                data=content.encode("utf-8"),
                headers=headers,
            )
        except WebDavError as exc:
            if "HTTP 412" in str(exc):
                raise NoteConflict("Notiz wurde zwischenzeitlich geaendert.") from exc
            raise

        if status not in {200, 201, 204}:
            raise WebDavError(f"WebDAV PUT -> unerwarteter Status {status}")


# ---------------------------------------------------------------------------
# Export-Ablauf
# ---------------------------------------------------------------------------


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="markdown_export.py",
        description=(
            "Fehlende Hausaufgaben des Tages append-only an die Obsidian-Notiz "
            "anhaengen (Standard: Nextcloud-WebDAV)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(_first_env("SCHULMANAGER_DB") or DEFAULT_DB_PATH),
        help="Pfad zur SQLite-Datenbank.",
    )
    parser.add_argument(
        "--stundenplan",
        type=Path,
        default=Path(
            _first_env("SCHULMANAGER_STUNDENPLAN") or DEFAULT_STUNDENPLAN_PATH
        ),
        help="Pfad zum Stundenplan (JSON).",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Zieldatum statt heute (Europe/Berlin).",
    )
    parser.add_argument(
        "--note-dir",
        type=Path,
        help="Lokales Notizverzeichnis statt WebDAV verwenden.",
    )
    parser.add_argument(
        "--dav-base",
        default=_first_env("NEXTCLOUD_DAV_BASE"),
        help="WebDAV-Basis-URL des Hausaufgaben-Ordners.",
    )
    parser.add_argument(
        "--dav-user",
        default=_first_env("NEXTCLOUD_USER", "NEXTCLOUD_USERNAME"),
        help="Nextcloud-Benutzername.",
    )
    parser.add_argument(
        "--dav-password",
        default=_first_env("NEXTCLOUD_PASSWORD"),
        help="Nextcloud-Passwort (besser: NEXTCLOUD_PASSWORD in .env).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur anzeigen, was angehaengt wuerde; nichts schreiben.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging aktivieren.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _make_store(args: argparse.Namespace):
    if args.note_dir:
        return LocalNoteStore(args.note_dir)

    missing = [
        name
        for name, value in (
            ("NEXTCLOUD_DAV_BASE", args.dav_base),
            ("NEXTCLOUD_USER", args.dav_user),
            ("NEXTCLOUD_PASSWORD", args.dav_password),
        )
        if not value
    ]
    if missing:
        raise ExportError(
            "WebDAV-Konfiguration fehlt: " + ", ".join(missing)
        )
    return WebDavNoteStore(args.dav_base, args.dav_user, args.dav_password)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(PROJECT_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        if args.date:
            try:
                target_date = date.fromisoformat(args.date)
            except ValueError as exc:
                raise ExportError(
                    f"Ungueltiges Datum: {args.date!r} (erwartet YYYY-MM-DD)"
                ) from exc
        else:
            target_date = datetime.now(BERLIN).date()

        now = datetime.now(BERLIN)
        timetable = load_timetable(args.stundenplan)
        records = load_homework_for_date(args.db, target_date)
        entries = build_entries(records, target_date, timetable)
        filename = f"{target_date.isoformat()}.md"

        LOGGER.info(
            "Export fuer %s: %d DB-Eintrag/Eintraege, Zieldatei %s",
            target_date.isoformat(),
            len(records),
            filename,
        )

        if not records:
            LOGGER.info("Keine Hausaufgaben fuer %s in der Datenbank.", target_date.isoformat())
            return 0

        store = _make_store(args)

        for attempt in range(1, 4):
            existing, etag = store.read(filename)
            update = build_note(existing, target_date, entries, now)

            if args.dry_run:
                if update.created:
                    LOGGER.info("Dry-Run: Notiz wuerde neu erstellt:")
                    print(update.content, end="")
                elif update.appended:
                    LOGGER.info(
                        "Dry-Run: %d Eintrag/Eintraege wuerden angehaengt:",
                        len(update.appended),
                    )
                    for entry in update.appended:
                        print(entry.line)
                else:
                    LOGGER.info("Dry-Run: Notiz ist bereits vollstaendig.")
                return 0

            if not update.appended:
                marked = mark_synchronized(args.db, [record.id for record in records])
                LOGGER.info(
                    "Notiz ist bereits vollstaendig; %d Datensatz/Datensaetze als "
                    "synchronisiert markiert.",
                    marked,
                )
                return 0

            try:
                store.write(filename, update.content, etag)
            except NoteConflict:
                LOGGER.warning(
                    "Notiz wurde waehrend des Schreibens geaendert, neuer Versuch (%d/3).",
                    attempt,
                )
                time.sleep(0.2)
                continue

            marked = mark_synchronized(args.db, [record.id for record in records])
            LOGGER.info(
                "%d Eintrag/Eintraege angehaengt (%s); %d Datensatz/Datensaetze als "
                "synchronisiert markiert.",
                len(update.appended),
                filename,
                marked,
            )
            return 0

        raise ExportError("Notiz konnte nach mehreren Versuchen nicht geschrieben werden.")

    except ExportError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Abgebrochen.")
        return 130
    except Exception:  # noqa: BLE001 - CLI soll mit klarer Meldung enden.
        LOGGER.exception("Unerwarteter Fehler.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
