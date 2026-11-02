"""Tests fuer Parser und Datenbank-Synchronisation."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import scraper


HTML_FIXTURE = """
<html>
  <body>
    <div class="tile">
      <div class="tile-header">Montag, 03.11.2026</div>
      <div class="tile-body">
        <h4>Mathematik</h4>
        <p class="homework-paragraph">S. 42, Nr. 1-5 ( bis morgen )</p>
      </div>
    </div>
    <div class="tile">
      <div class="tile-header">Dienstag, 04.11.2026</div>
      <div class="tile-body">
        <h4>Deutsch</h4>
        <p class="homework-paragraph">Leseheft Seite 16</p>
        <h4>Englisch</h4>
        <p class="homework-paragraph">WB S. 23 Nr. 2</p>
      </div>
    </div>
    <div class="tile">
      <div class="tile-body">
        <h4>Biologie</h4>
        <p class="homework-paragraph">Vokabeln lernen</p>
      </div>
    </div>
  </body>
</html>
"""


def test_parse_homework():
    homework = scraper.parse_homework(HTML_FIXTURE)
    assert len(homework) == 4
    assert homework[0] == {
        "datum": "Montag, 03.11.2026",
        "fach": "Mathematik",
        "inhalt": "S. 42, Nr. 1-5 ( bis morgen )",
    }
    assert homework[2] == {
        "datum": "Dienstag, 04.11.2026",
        "fach": "Englisch",
        "inhalt": "WB S. 23 Nr. 2",
    }
    assert homework[3] == {
        "datum": "",
        "fach": "Biologie",
        "inhalt": "Vokabeln lernen",
    }


def test_generate_homework_id():
    expected = hashlib.md5(
        "Mathematik_Montag, 03.11.2026_S. 42, Nr. 1-5".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    assert scraper.generate_homework_id(
        "Mathematik", "Montag, 03.11.2026", "S. 42, Nr. 1-5"
    ) == expected


def test_sync_homework_to_db(tmp_path: Path):
    db_path = tmp_path / "hausaufgaben.db"
    homework = scraper.parse_homework(HTML_FIXTURE)

    inserted, skipped = scraper.sync_homework_to_db(homework, db_path)
    assert inserted == 4
    assert skipped == 0

    inserted2, skipped2 = scraper.sync_homework_to_db(homework, db_path)
    assert inserted2 == 0
    assert skipped2 == 4

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, datum, fach, inhalt, synchronisiert FROM homework ORDER BY id"
        ).fetchall()
    assert len(rows) == 4
    for row in rows:
        assert isinstance(row["id"], str) and len(row["id"]) == 32
        assert row["synchronisiert"] == 0

    raw = f"{rows[0]['fach']}_{rows[0]['datum']}_{rows[0]['inhalt']}"
    assert rows[0]["id"] == hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def test_parse_homework_ignores_missing_paragraph(tmp_path: Path):
    html = """
    <div class="tile">
      <div class="tile-header">Freitag, 07.11.2026</div>
      <div class="tile-body">
        <h4>Geschichte</h4>
      </div>
    </div>
    """
    homework = scraper.parse_homework(html)
    assert homework == []
    inserted, skipped = scraper.sync_homework_to_db(homework, tmp_path / "leer.db")
    assert inserted == 0
    assert skipped == 0


def test_parse_homework_nested_paragraph():
    html = """
    <div class="tile">
      <div class="tile-header">Mittwoch, 05.11.2026</div>
      <div class="tile-body">
        <h4>Physik</h4>
        <div class="wrapper">
          <p class="homework-paragraph">Experiment vorbereiten</p>
        </div>
      </div>
    </div>
    """
    assert scraper.parse_homework(html) == [
        {
            "datum": "Mittwoch, 05.11.2026",
            "fach": "Physik",
            "inhalt": "Experiment vorbereiten",
        }
    ]


def test_parse_homework_does_not_reuse_next_subject_paragraph():
    html = """
    <div class="tile">
      <div class="tile-header">Donnerstag, 06.11.2026</div>
      <div class="tile-body">
        <h4>Mathematik</h4>
        <h4>Deutsch</h4>
        <p class="homework-paragraph">Aufsatz schreiben</p>
      </div>
    </div>
    """
    assert scraper.parse_homework(html) == [
        {
            "datum": "Donnerstag, 06.11.2026",
            "fach": "Deutsch",
            "inhalt": "Aufsatz schreiben",
        }
    ]


def test_is_login_url_ignores_login_hostname():
    assert scraper._is_login_url("https://login.schulmanager-online.de/#/login")
    assert scraper._is_login_url("https://login.schulmanager-online.de/login")
    assert not scraper._is_login_url(
        "https://login.schulmanager-online.de/#/modules/classbook/homework/"
    )
