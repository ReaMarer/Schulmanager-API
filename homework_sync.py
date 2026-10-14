from datetime import datetime
from bs4 import BeautifulSoup
from markdown_writer import write_homework_markdown

def parse_and_sync_locally():
    wochentage = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag"
    }
    now = datetime.now()
    heute_eng = now.strftime("%A")
    heute_de = wochentage.get(heute_eng, "Montag")
    datum_str = now.strftime("%d.%m.%Y")
    heutiges_ziel_datum = f"{heute_de}, {datum_str}"
    
    iso_datum = now.strftime("%Y-%m-%d")

    print(f"[Sync] Starte Analyse für: {heutiges_ziel_datum}")

    try:
        with open("raw_homework.html", "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except FileNotFoundError:
        print("[Sync] Fehler: 'raw_homework.html' wurde nicht gefunden.")
        return

    # Auf der Website heißen die Kacheln schlicht "tile"
    tiles = soup.find_all("div", class_="tile")
    if not tiles:
        print("[Sync] Keine Hausaufgaben-Kacheln (div.tile) im HTML gefunden. Breche ab.")
        return
        
    target_tile = None
    
    # Gehe alle Kacheln durch und finde die mit dem heutigen Datum
    for tile in tiles:
        header = tile.find("div", class_="tile-header")
        if header and datum_str in header.text:
            target_tile = tile
            heutiges_ziel_datum = header.text.strip()
            break

    if not target_tile:
        print(f"[Sync] Keine Hausaufgaben-Kachel für heute ({datum_str}) gefunden. Breche ab.")
        return

    # Übergabe an das Markdown-Writer Skript (iso_datum bleibt fix das heutige Datum)
    write_homework_markdown(iso_datum, heutiges_ziel_datum, target_tile)

if __name__ == "__main__":
    parse_and_sync_locally()