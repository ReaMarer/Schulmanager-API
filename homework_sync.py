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

    target_tile = soup.find("div", class_="classbook-homework-tile") # Oder einfach class_="tile"
    if not target_tile:
        print("[Sync] Keine Hausaufgaben-Kacheln im HTML gefunden. Breche ab.")
        return
        
    # Extrahiere das echte Datum aus der gefundenen Kachel
    header = target_tile.find("div", class_="tile-header")
    if header:
        heutiges_ziel_datum = header.text.strip()
        # Versuche das Datum aus dem Header zu extrahieren (Format: "Wochentag, DD.MM.YYYY")
        try:
            raw_date = heutiges_ziel_datum.split(",")[1].strip()
            date_obj = datetime.strptime(raw_date, "%d.%m.%Y")
            iso_datum = date_obj.strftime("%Y-%m-%d")
        except Exception:
            print("[Sync] Konnte Datum aus Header nicht parsen. Nutze aktuelles Tagesdatum.")


    if not target_tile:
        print(f"[Sync] Keine Hausaufgaben für {heutiges_ziel_datum} gefunden. Breche ab.")
        return

    # Übergabe an das Markdown-Writer Skript
    write_homework_markdown(iso_datum, heutiges_ziel_datum, target_tile)

if __name__ == "__main__":
    parse_and_sync_locally()