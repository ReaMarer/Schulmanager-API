"""Zusaetzliche Parser-Tests fuer mehrzeilige Hausaufgaben."""

from __future__ import annotations

import scraper


def test_parse_homework_preserves_multiline_content():
    html = """
    <div class="tile">
      <div class="tile-header">Donnerstag, 15.10.2026</div>
      <div class="tile-body">
        <h4>Englisch</h4>
        <p class="homework-paragraph"><span style="white-space: pre-wrap;">
          Revise the vocabulary Unit 1
          Buy the novel
          Learn for the class test
        </span></p>
      </div>
    </div>
    """
    assert scraper.parse_homework(html) == [
        {
            "datum": "Donnerstag, 15.10.2026",
            "fach": "Englisch",
            "inhalt": (
                "Revise the vocabulary Unit 1\n"
                "Buy the novel\n"
                "Learn for the class test"
            ),
        }
    ]
