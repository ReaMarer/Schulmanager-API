"""Tests fuer den append-only Markdown-Export."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import markdown_export
import scraper
from markdown_export import (
    BERLIN,
    ExportEntry,
    HomeworkRecord,
    build_entries,
    build_note,
    entry_identity,
    load_homework_for_date,
    mark_synchronized,
    next_lesson_date,
    parse_homework_date,
)

NOW = datetime(2026, 10, 14, 23, 0, 7, tzinfo=BERLIN)
TARGET = date(2026, 10, 14)

TIMETABLE = {
    "Montag": ["Informatik", "Mathematik", "Latein", "Englisch"],
    "Dienstag": ["Mathematik", "Praktische Philosophie", "Latein"],
    "Mittwoch": ["Deutsch", "Praktische Philosophie", "Chemie"],
    "Donnerstag": ["Englisch", "Sport", "Deutsch", "Physik"],
    "Freitag": ["Informatik", "Geschichte"],
}


def test_parse_homework_date() -> None:
    assert parse_homework_date("Mittwoch, 14.10.2026") == date(2026, 10, 14)
    assert parse_homework_date("2026-10-14") == date(2026, 10, 14)
    assert parse_homework_date("") is None
    assert parse_homework_date("31.02.2026") is None


def test_next_lesson_date_uses_next_matching_weekday() -> None:
    # Mittwoch -> naechster Dienstag bzw. Mittwoch
    assert next_lesson_date(TARGET, "PRAKTISCHE PHIL.", TIMETABLE) == date(2026, 10, 20)
    assert next_lesson_date(TARGET, "Chemie", TIMETABLE) == date(2026, 10, 21)
    assert next_lesson_date(TARGET, "Unbekannt", TIMETABLE) == date(2026, 10, 15)


def test_entry_identity_ignores_status_and_metadata() -> None:
    assert (
        entry_identity("**Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫")
        == "**Chemie**: Keine HA"
    )
    assert (
        entry_identity("**Mathematik**: Seite 4 ⏫ ➕ 2026-10-13 📅 2026-10-14 ✅ 2026-10-14")
        == "**Mathematik**: Seite 4"
    )


def test_build_entries_splits_multiline_and_calculates_due_dates() -> None:
    records = [
        HomeworkRecord(id="1", fach="PRAKTISCHE PHIL.", inhalt="Keine HA"),
        HomeworkRecord(
            id="2",
            fach="Englisch",
            inhalt="Revise the vocabulary\nBuy the novel",
        ),
        HomeworkRecord(id="3", fach="Englisch", inhalt="Revise the vocabulary"),
    ]

    entries = build_entries(records, TARGET, TIMETABLE)

    assert [entry.line for entry in entries] == [
        "- [ ] **PRAKTISCHE PHIL.**: Keine HA 📅 2026-10-20 ➕ 2026-10-14 ⏫",
        "- [ ] **Englisch**: Revise the vocabulary 📅 2026-10-15 ➕ 2026-10-14 ⏫",
        "- [ ] **Englisch**: Buy the novel 📅 2026-10-15 ➕ 2026-10-14 ⏫",
    ]


def test_build_note_creates_full_note() -> None:
    entries = build_entries(
        [HomeworkRecord(id="1", fach="Chemie", inhalt="Keine HA")],
        TARGET,
        TIMETABLE,
    )

    update = build_note(None, TARGET, entries, NOW)

    assert update.created is True
    assert update.appended == tuple(entries)
    assert update.content == (
        "---\n"
        "date: 2026-10-14\n"
        "last_updated: 2026-10-14 23:00:07\n"
        "tags:\n"
        "  - schule\n"
        "  - hausaufgaben\n"
        "---\n"
        "# 📚 Hausaufgaben für Mittwoch, 14.10.2026\n"
        "- [ ] **Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫\n"
    )


EXISTING_NOTE = """---
date: 2026-10-14
last_updated: 2026-10-14 22:00:00
tags:
  - schule
  - hausaufgaben
---
# 📚 Hausaufgaben für Mittwoch, 14.10.2026
- [ ] **PRAKTISCHE PHIL.**: Keine HA 📅 2026-10-20 ➕ 2026-10-14 ⏫
"""


def test_build_note_appends_only_missing_and_keeps_existing_lines() -> None:
    entries = build_entries(
        [
            HomeworkRecord(id="1", fach="PRAKTISCHE PHIL.", inhalt="Keine HA"),
            HomeworkRecord(id="2", fach="Chemie", inhalt="Keine HA"),
        ],
        TARGET,
        TIMETABLE,
    )

    update = build_note(EXISTING_NOTE, TARGET, entries, NOW)

    assert update.created is False
    assert [entry.identity for entry in update.appended] == ["**Chemie**: Keine HA"]
    lines = update.content.splitlines()
    assert lines[2] == "last_updated: 2026-10-14 23:00:07"
    # Die bestehende Aufgabenzeile bleibt unveraendert erhalten.
    assert (
        "- [ ] **PRAKTISCHE PHIL.**: Keine HA 📅 2026-10-20 ➕ 2026-10-14 ⏫"
        in lines
    )
    assert lines[-1] == "- [ ] **Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫"


def test_build_note_leaves_complete_note_untouched() -> None:
    entries = [
        ExportEntry(
            identity="**PRAKTISCHE PHIL.**: Keine HA",
            line="- [ ] **PRAKTISCHE PHIL.**: Keine HA 📅 2026-10-20 ➕ 2026-10-14 ⏫",
        )
    ]

    update = build_note(EXISTING_NOTE, TARGET, entries, NOW)

    assert update.content == EXISTING_NOTE
    assert update.appended == ()
    assert update.created is False


def test_build_note_adds_missing_header() -> None:
    existing = "---\ndate: 2026-10-14\n---\n"
    entries = build_entries(
        [HomeworkRecord(id="1", fach="Chemie", inhalt="Keine HA")],
        TARGET,
        TIMETABLE,
    )

    update = build_note(existing, TARGET, entries, NOW)

    assert update.content.startswith(existing)
    assert "# 📚 Hausaufgaben für Mittwoch, 14.10.2026" in update.content
    assert update.content.rstrip().endswith(
        "- [ ] **Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫"
    )


def test_build_note_deduplicates_duplicate_entries() -> None:
    entry = ExportEntry(
        identity="**Chemie**: Keine HA",
        line="- [ ] **Chemie**: Keine HA 📅 2026-10-21 ➕ 2026-10-14 ⏫",
    )

    update = build_note(None, TARGET, [entry, entry], NOW)

    assert update.content.count("**Chemie**: Keine HA") == 1


def test_load_homework_for_date_filters_and_keeps_order(tmp_path: Path) -> None:
    db_path = tmp_path / "hausaufgaben.db"
    scraper.sync_homework_to_db(
        [
            {"datum": "Mittwoch, 14.10.2026", "fach": "Chemie", "inhalt": "Keine HA"},
            {"datum": "Donnerstag, 15.10.2026", "fach": "Englisch", "inhalt": "Test"},
            {"datum": "Mittwoch, 14.10.2026", "fach": "Deutsch", "inhalt": "Aufsatz"},
        ],
        db_path,
    )

    records = load_homework_for_date(db_path, TARGET)

    assert [record.fach for record in records] == ["Chemie", "Deutsch"]
    assert all(record.inhalt for record in records)


def test_mark_synchronized_updates_only_given_ids(tmp_path: Path) -> None:
    db_path = tmp_path / "hausaufgaben.db"
    scraper.sync_homework_to_db(
        [
            {"datum": "Mittwoch, 14.10.2026", "fach": "Chemie", "inhalt": "Keine HA"},
            {"datum": "Mittwoch, 14.10.2026", "fach": "Deutsch", "inhalt": "Aufsatz"},
        ],
        db_path,
    )
    records = load_homework_for_date(db_path, TARGET)

    marked = mark_synchronized(db_path, [records[0].id])

    assert marked == 1
    with sqlite3.connect(db_path) as connection:
        rows = dict(connection.execute("SELECT fach, synchronisiert FROM homework"))
    assert rows == {"Chemie": 1, "Deutsch": 0}


def test_main_append_only_integration(tmp_path: Path) -> None:
    db_path = tmp_path / "hausaufgaben.db"
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    note_path = notes_dir / "2026-10-14.md"
    note_path.write_text(EXISTING_NOTE, encoding="utf-8")

    scraper.sync_homework_to_db(
        [
            {
                "datum": "Mittwoch, 14.10.2026",
                "fach": "PRAKTISCHE PHIL.",
                "inhalt": "Keine HA",
            },
            {"datum": "Mittwoch, 14.10.2026", "fach": "Chemie", "inhalt": "Keine HA"},
        ],
        db_path,
    )

    argv = [
        "--db",
        str(db_path),
        "--stundenplan",
        str(markdown_export.DEFAULT_STUNDENPLAN_PATH),
        "--date",
        "2026-10-14",
        "--note-dir",
        str(notes_dir),
    ]

    assert markdown_export.main(argv) == 0
    first_content = note_path.read_text(encoding="utf-8")
    assert "**PRAKTISCHE PHIL.**: Keine HA" in first_content
    assert "**Chemie**: Keine HA" in first_content

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM homework WHERE synchronisiert = 1"
        ).fetchone()[0] == 2

    # Ein zweiter Lauf darf die Notiz nicht mehr veraendern.
    assert markdown_export.main(argv) == 0
    assert note_path.read_text(encoding="utf-8") == first_content
