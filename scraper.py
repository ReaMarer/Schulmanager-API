#!/usr/bin/env python3
"""Schulmanager Online: Hausaufgaben scrapen und in SQLite synchronisieren.

Das Skript meldet sich mit den Zugangsdaten aus der Umgebung (oder per CLI)
bei Schulmanager Online an, ruft die Hausaufgaben-Ansicht ab, parst die
Kacheln und speichert neue Eintraege in ``hausaufgaben.db``. Bereits
vorhandene Eintraege werden ueber einen MD5-Primary-Key erkannt und
uebersprungen.

Beispiel:
    export SCHULMANAGER_EMAIL="vorname.nachname@example.com"
    export SCHULMANAGER_PASSWORD="geheim"
    .venv/bin/python scraper.py

Offline-Verarbeitung einer gespeicherten HTML-Datei:
    .venv/bin/python scraper.py --input-html seite.html --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Sequence, TypedDict
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from playwright.sync_api import (
    Browser,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

__version__ = "1.0.0"

LOGGER = logging.getLogger("schulmanager")

LOGIN_URL = "https://login.schulmanager-online.de/#/login"
HOMEWORK_URL = "https://login.schulmanager-online.de/#/modules/classbook/homework/"
HOMEWORK_ROUTE_MARKER = "/modules/classbook/homework"

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path("hausaufgaben.db")
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_TILE_TIMEOUT_SECONDS = 15
HOMEWORK_CONTENT_TIMEOUT_MS = 5_000
NETWORK_IDLE_TIMEOUT_MS = 10_000

COOKIE_BUTTON_SELECTORS = (
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Zustimmen')",
    "button:has-text('Einverstanden')",
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
)

LOGIN_ERROR_SELECTORS = (
    ".alert-danger",
    ".alert",
    "[role='alert']",
    ".invalid-feedback",
    ".error-message",
    ".toast-error",
)


class Homework(TypedDict):
    """Eine einzelne Hausaufgabe, wie sie aus einer Kachel gelesen wird."""

    datum: str
    fach: str
    inhalt: str


class ScraperError(RuntimeError):
    """Fehler, der dem Benutzer verstaendlich angezeigt werden kann."""


class LoginError(ScraperError):
    """Anmeldung bei Schulmanager Online fehlgeschlagen."""


class DatabaseError(ScraperError):
    """Fehler beim Zugriff auf die SQLite-Datenbank."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _clean_text(value: str) -> str:
    """Whitespace (inkl. Umbruechen) zu einer Zeile vereinheitlichen.

    Das sorgt fuer stabile Hashes: Dieselbe Hausaufgabe erzeugt auch dann
    dieselbe ID, wenn das HTML unterschiedlich eingerueckt ist.
    """

    return " ".join(value.split())


def _clean_content(value: str) -> str:
    """Inhalt zeilenweise bereinigen, absichtliche Umbrueche aber behalten.

    Schulmanager speichert mehrere Aufgaben eines Fachs teils als mehrzeiligen
    Text in einem ``p.homework-paragraph``. Diese Zeilen sollen in der
    Datenbank lesbar bleiben, waehrend Einrueckungen/Leerzeilen verschwinden.
    """

    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _find_homework_paragraph(heading: Tag, body: Tag) -> Tag | None:
    """Finde den Inhalt ``p.homework-paragraph`` direkt unter einer ``h4``.

    Bevorzugt wird das unmittelbar folgende Geschwisterelement. Falls das
    Markup dazwischen weitere Elemente enthaelt, wird das naechste passende
    ``p`` innerhalb derselben Kachel verwendet.
    """

    for sibling in heading.next_siblings:
        if not isinstance(sibling, Tag):
            continue
        if sibling.name == "h4":
            break
        if sibling.name == "p" and "homework-paragraph" in (sibling.get("class") or []):
            return sibling

    candidate = heading.find_next("p", class_="homework-paragraph")
    if candidate is None or not any(parent is body for parent in candidate.parents):
        return None

    # Nicht versehentlich den Inhalt des naechsten Fachs uebernehmen, wenn
    # fuer das aktuelle Fach kein Absatz vorhanden ist.
    next_heading = heading.find_next("h4")
    if next_heading is not None and any(
        element is candidate for element in next_heading.find_all_next()
    ):
        return None

    return candidate


def parse_homework(html: str) -> list[Homework]:
    """Parse alle Hausaufgaben aus dem HTML der Hausaufgaben-Ansicht.

    Erwartetes Markup (vereinfacht)::

        <div class="tile">
          <div class="tile-header">Montag, 03.11.2026</div>
          <div class="tile-body">
            <h4>Mathematik</h4>
            <p class="homework-paragraph">S. 42, Nr. 1-5</p>
          </div>
        </div>

    Returns:
        Liste von Dictionaries mit den Schluesseln ``datum``, ``fach`` und
        ``inhalt``. Kacheln ohne verwertbaren Inhalt werden uebersprungen.
    """

    soup = BeautifulSoup(html, "html.parser")
    homework: list[Homework] = []

    for tile in soup.find_all("div", class_="tile"):
        header = tile.find("div", class_="tile-header")
        body = tile.find("div", class_="tile-body")
        if body is None:
            continue

        datum = _clean_text(header.get_text(" ", strip=True)) if header else ""

        for heading in body.find_all("h4"):
            fach = _clean_text(heading.get_text(" ", strip=True))
            paragraph = _find_homework_paragraph(heading, body)
            if paragraph is None:
                LOGGER.debug("Kein homework-paragraph fuer Fach %r gefunden.", fach)
                continue

            inhalt = _clean_content(paragraph.get_text(" ", strip=False))
            if not fach and not inhalt:
                continue

            homework.append({"datum": datum, "fach": fach, "inhalt": inhalt})

    return homework


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------


def generate_homework_id(fach: str, datum: str, inhalt: str) -> str:
    """Erzeuge die deterministische MD5-ID einer Hausaufgabe.

    Das Format entspricht exakt ``f"{fach}_{datum}_{inhalt}"``. Dadurch
    verhindert der Primary Key doppelte Eintraege bei wiederholten Laeufen.
    """

    raw = f"{fach}_{datum}_{inhalt}"
    return hashlib.md5(raw.encode("utf-8"), usedforsecurity=False).hexdigest()


def _open_database(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DatabaseError(
            f"Datenbankverzeichnis konnte nicht erstellt werden: {path.parent}"
        ) from exc

    try:
        return sqlite3.connect(path, timeout=10.0)
    except sqlite3.Error as exc:
        raise DatabaseError(f"Datenbank konnte nicht geoeffnet werden: {path}") from exc


def sync_homework_to_db(
    homework: Sequence[Homework],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    """Synchronisiere geparste Hausaufgaben mit der SQLite-Datenbank.

    Neue Datensaetze werden eingefuegt. Existiert die MD5-ID bereits, faengt
    ``sqlite3.IntegrityError`` den Konflikt ab und der Eintrag wird
    uebersprungen.

    Returns:
        Tupel ``(inserted_count, skipped_count)``.
    """

    inserted_count = 0
    skipped_count = 0
    connection = _open_database(db_path)

    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS homework (
                    id TEXT PRIMARY KEY,
                    datum TEXT,
                    fach TEXT,
                    inhalt TEXT,
                    synchronisiert INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            for item in homework:
                homework_id = generate_homework_id(
                    fach=item["fach"],
                    datum=item["datum"],
                    inhalt=item["inhalt"],
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO homework (id, datum, fach, inhalt)
                        VALUES (?, ?, ?, ?)
                        """,
                        (homework_id, item["datum"], item["fach"], item["inhalt"]),
                    )
                except sqlite3.IntegrityError:
                    skipped_count += 1
                    LOGGER.debug(
                        "Bereits vorhanden, uebersprungen: %s | %s",
                        item["datum"] or "-",
                        item["fach"] or "-",
                    )
                else:
                    inserted_count += 1
    except sqlite3.Error as exc:
        raise DatabaseError(
            f"Datenbankfehler bei {Path(db_path).expanduser()}: {exc}"
        ) from exc
    finally:
        connection.close()

    return inserted_count, skipped_count


# ---------------------------------------------------------------------------
# Browser-Automation
# ---------------------------------------------------------------------------


def _is_login_url(url: str) -> bool:
    """Pruefe Pfad/Fragment auf die Login-Route.

    Wichtig: Der Hostname lautet selbst ``login.schulmanager-online.de``.
    Deshalb darf nur der Pfad bzw. das Hash-Fragment geprueft werden, nicht
    die komplette URL.
    """

    parsed = urlparse(url)
    route = f"{parsed.path} {parsed.fragment}".lower()
    return "/login" in route


def _is_login_page(page: Page) -> bool:
    return _is_login_url(page.url)


def _dismiss_cookie_banner(page: Page) -> None:
    """Klicke, falls vorhanden, einen Cookie-Zustimmen-Button weg."""

    # Der Banner wird von manchen SPAs erst nach DOMContentLoaded gerendert.
    page.wait_for_timeout(500)
    for selector in COOKIE_BUTTON_SELECTORS:
        button = page.locator(selector).first
        try:
            if button.is_visible():
                button.click(timeout=2_000)
                LOGGER.debug("Cookie-Banner ueber %r geschlossen.", selector)
                page.wait_for_timeout(300)
                return
        except PlaywrightError:
            continue


def _read_login_error(page: Page) -> str:
    """Lies sichtbare Fehlermeldungen der Login-Seite (falls vorhanden)."""

    messages: list[str] = []
    for selector in LOGIN_ERROR_SELECTORS:
        locator = page.locator(selector)
        try:
            for index in range(min(locator.count(), 5)):
                element = locator.nth(index)
                if not element.is_visible():
                    continue
                text = _clean_text(element.inner_text())
                if text and text not in messages:
                    messages.append(text)
        except PlaywrightError:
            continue
    return " | ".join(messages)


def _login(page: Page, email: str, password: str, timeout_ms: int) -> None:
    LOGGER.info("Rufe Login-Seite auf ...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise LoginError(
            "Login-Seite konnte nicht geladen werden (Zeitueberschreitung)."
        ) from exc
    except PlaywrightError as exc:
        raise LoginError(f"Login-Seite konnte nicht geladen werden: {exc}") from exc

    _dismiss_cookie_banner(page)

    try:
        page.wait_for_selector(
            "input[name='emailOrUsername']",
            state="visible",
            timeout=timeout_ms,
        )
        page.fill("input[name='emailOrUsername']", email)
        page.fill("input[name='password']", password)
        page.click("button:has-text('Einloggen')")
        LOGGER.info("Zugangsdaten uebermittelt, warte auf Anmeldung ...")
        page.wait_for_function(
            "() => !window.location.hash.toLowerCase().includes('/login')",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError as exc:
        details = _read_login_error(page)
        if details:
            raise LoginError(f"Login fehlgeschlagen: {details}") from exc
        raise LoginError(
            "Login fehlgeschlagen (Zeitueberschreitung). Bitte E-Mail/Passwort pruefen."
        ) from exc
    except PlaywrightError as exc:
        raise LoginError(f"Login fehlgeschlagen: {exc}") from exc

    # Die App laedt nach dem Login asynchron weitere Daten. networkidle ist
    # optional, da manche SPAs dauerhaft pollen.
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        LOGGER.debug("networkidle nicht erreicht, fahre trotzdem fort.")

    if _is_login_page(page):
        details = _read_login_error(page)
        message = "Login fehlgeschlagen"
        if details:
            message += f": {details}"
        raise LoginError(message)

    LOGGER.info("Anmeldung erfolgreich.")


def _load_homework_html(page: Page, timeout_ms: int, tile_timeout_ms: int) -> str:
    LOGGER.info("Navigiere zur Hausaufgaben-Ansicht ...")
    try:
        page.goto(HOMEWORK_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise ScraperError(
            "Hausaufgaben-Seite konnte nicht geladen werden (Zeitueberschreitung)."
        ) from exc
    except PlaywrightError as exc:
        raise ScraperError(f"Hausaufgaben-Seite konnte nicht geladen werden: {exc}") from exc

    # Die Anwendung ist eine SPA. Ein direktes goto auf eine Hash-Route laedt
    # sonst u.U. noch das Dashboard, dessen Kacheln ebenfalls ``div.tile``
    # verwenden. Deshalb zuerst warten, bis die Hausaufgaben-Route aktiv ist.
    try:
        page.wait_for_function(
            "(marker) => window.location.hash.toLowerCase().includes(marker)",
            arg=HOMEWORK_ROUTE_MARKER,
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError as exc:
        if _is_login_page(page):
            raise LoginError(
                "Sitzung wurde beendet; die Hausaufgaben-Seite verlangt erneut Login."
            ) from exc
        raise ScraperError(
            "Die Hausaufgaben-Ansicht wurde nicht geoeffnet (Zeitueberschreitung)."
        ) from exc

    try:
        page.wait_for_selector("div.tile", timeout=tile_timeout_ms)
    except PlaywrightTimeoutError:
        if _is_login_page(page) or page.locator("input[name='password']").count() > 0:
            raise LoginError(
                "Sitzung wurde beendet; die Hausaufgaben-Seite verlangt erneut Login."
            )
        LOGGER.warning(
            "Keine Hausaufgaben-Kacheln gefunden (moeglicherweise keine Hausaufgaben). "
            "Fahre mit dem aktuellen Seiteninhalt fort."
        )

    # Sicherstellen, dass nicht noch die Dashboard-Kacheln gelesen werden.
    try:
        page.wait_for_selector(
            "p.homework-paragraph",
            timeout=min(HOMEWORK_CONTENT_TIMEOUT_MS, tile_timeout_ms),
        )
    except PlaywrightTimeoutError:
        LOGGER.debug("Keine homework-paragraph-Elemente gefunden.")

    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        LOGGER.debug("networkidle nicht erreicht, lese aktuellen Seiteninhalt.")

    return page.content()


def _launch_browser(playwright, headless: bool) -> Browser:
    try:
        return playwright.chromium.launch(headless=headless)
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise ScraperError(
                "Chromium ist fuer Playwright nicht installiert. Bitte ausfuehren: "
                "'.venv/bin/playwright install chromium'."
            ) from exc
        raise ScraperError(f"Browser konnte nicht gestartet werden: {exc}") from exc


def fetch_homework_html(
    email: str,
    password: str,
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_SECONDS * 1000,
    tile_timeout_ms: int = DEFAULT_TILE_TIMEOUT_SECONDS * 1000,
    dump_html: str | Path | None = None,
) -> str:
    """Melde dich an und liefere das HTML der Hausaufgaben-Ansicht."""

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless)
        context = None
        try:
            context = browser.new_context(
                locale="de-DE",
                timezone_id="Europe/Berlin",
                viewport={"width": 1440, "height": 900},
            )
            context.set_default_timeout(timeout_ms)
            page = context.new_page()
            _login(page, email, password, timeout_ms)
            html = _load_homework_html(page, timeout_ms, tile_timeout_ms)
        finally:
            if context is not None:
                try:
                    context.close()
                except PlaywrightError:
                    pass
            try:
                browser.close()
            except PlaywrightError:
                pass

    if dump_html:
        output_path = Path(dump_html).expanduser()
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html, encoding="utf-8")
            LOGGER.info("HTML gespeichert unter %s", output_path)
        except OSError as exc:
            LOGGER.warning("HTML konnte nicht gespeichert werden: %s", exc)

    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper.py",
        description=(
            "Schulmanager-Online-Hausaufgaben abrufen und in SQLite "
            "synchronisieren (Duplikatschutz per MD5-ID)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--email",
        default=_env("SCHULMANAGER_EMAIL", "SCHULMANAGER_USERNAME", "SCHULMANAGER_USER"),
        help="Schulmanager-E-Mail/Benutzername (besser: SCHULMANAGER_EMAIL).",
    )
    parser.add_argument(
        "--password",
        default=_env("SCHULMANAGER_PASSWORD"),
        help="Schulmanager-Passwort (besser: SCHULMANAGER_PASSWORD).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(_env("SCHULMANAGER_DB", default=str(DEFAULT_DB_PATH)) or DEFAULT_DB_PATH),
        help="Pfad zur SQLite-Datenbank.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SEKUNDEN",
        help="Timeout fuer Login/Navigation.",
    )
    parser.add_argument(
        "--tile-timeout",
        type=int,
        default=DEFAULT_TILE_TIMEOUT_SECONDS,
        metavar="SEKUNDEN",
        help="Timeout zum Warten auf die Hausaufgaben-Kacheln.",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Browser sichtbar starten (Debugging).",
    )
    parser.set_defaults(headless=_env_bool("SCHULMANAGER_HEADLESS", True))
    parser.add_argument(
        "--dump-html",
        type=Path,
        metavar="DATEI",
        help="Geladenes HTML fuer Debugging speichern.",
    )
    parser.add_argument(
        "--input-html",
        type=Path,
        metavar="DATEI",
        help="Offline-Modus: HTML aus Datei parsen statt Browser zu verwenden.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hausaufgaben nur anzeigen, nicht in die Datenbank schreiben.",
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


def _read_html_file(path: Path) -> str:
    try:
        return path.expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise ScraperError(f"HTML-Datei konnte nicht gelesen werden ({path}): {exc}") from exc


def _print_homework(homework: Sequence[Homework]) -> None:
    for index, item in enumerate(homework, start=1):
        LOGGER.info(
            "[%d] %s | %s | %s",
            index,
            item["datum"] or "-",
            item["fach"] or "-",
            item["inhalt"] or "-",
        )


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(PROJECT_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    if args.timeout <= 0 or args.tile_timeout <= 0:
        LOGGER.error("Timeouts muessen groesser als 0 sein.")
        return 2

    try:
        if args.input_html is not None:
            LOGGER.info("Offline-Modus: lese HTML aus %s", args.input_html)
            html = _read_html_file(args.input_html)
        else:
            if not args.email or not args.password:
                LOGGER.error(
                    "Zugangsdaten fehlen. Bitte SCHULMANAGER_EMAIL und "
                    "SCHULMANAGER_PASSWORD setzen (oder --email/--password uebergeben)."
                )
                return 2
            html = fetch_homework_html(
                args.email,
                args.password,
                headless=args.headless,
                timeout_ms=args.timeout * 1000,
                tile_timeout_ms=args.tile_timeout * 1000,
                dump_html=args.dump_html,
            )

        homework = parse_homework(html)
        LOGGER.info("%d Hausaufgabe(n) gefunden.", len(homework))

        if args.dry_run:
            _print_homework(homework)
            LOGGER.info("Dry-Run: Datenbank wurde nicht veraendert.")
            return 0

        inserted, skipped = sync_homework_to_db(homework, args.db)
        LOGGER.info(
            "Synchronisation abgeschlossen: %d neu, %d bereits vorhanden (%s).",
            inserted,
            skipped,
            args.db,
        )
        return 0

    except LoginError as exc:
        LOGGER.error("Login-Fehler: %s", exc)
        return 1
    except ScraperError as exc:
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
