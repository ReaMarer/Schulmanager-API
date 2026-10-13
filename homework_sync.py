from datetime import datetime
from bs4 import BeautifulSoup
from markdown_writer import write_homework_markdown  # Import der neuen Datei

def parse_and_sync_locally():
    wochentage = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag"
    }
    heute_eng = datetime.now().strftime("%A")
    heute_de = wochentage.get(heute_eng, "Montag")
    datum_str = datetime.now().strftime("%d.%m.%Y")
    heutiges_ziel_datum = f"{heute_de}, {datum_str}"
    
    iso_datum = datetime.now().strftime("%Y-%m-%d")

    print(f"[Sync] Starte Analyse für: {heutiges_ziel_datum}")

    try:
        with open("raw_homework.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except FileNotFoundError:
        print("[Sync] Fehler: 'raw_homework.html' wurde nicht gefunden.")
        return

    # Die exakte Schulmanager-Tile-Struktur für das Datum finden
    target_tile = None
    for tile in soup.find_all("div", class_="tile"):
        header = tile.find("div", class_="tile-header")
        if header and heutiges_ziel_datum in header.text:
            target_tile = tile
            break

    if not target_tile:
        print(f"[Sync] Keine Hausaufgaben für {heutiges_ziel_datum} gefunden. Breche ab.")
        return

    # Übergabe an das Markdown-Writer Skript
    write_homework_markdown(iso_datum, heutiges_ziel_datum, target_tile)

if __name__ == "__main__":
    parse_and_sync_locally()