import os
from datetime import datetime
from bs4 import BeautifulSoup

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

    # Die exakte Schulmanager-Tile-Struktur für das Datum finden[cite: 8]
    target_tile = None
    for tile in soup.find_all("div", class_="tile"):
        header = tile.find("div", class_="tile-header")
        if header and heutiges_ziel_datum in header.text:
            target_tile = tile
            break

    if not target_tile:
        print(f"[Sync] Keine Hausaufgaben für {heutiges_ziel_datum} gefunden. Breche ab.")
        return

    # Markdown-Inhalt generieren
    md_lines = [
        "---",
        f"date: {iso_datum}",
        f"last_updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "tags:",
        "  - schule",
        "  - hausaufgaben",
        "---",
        f"# 📚 Hausaufgaben für {heutiges_ziel_datum}",
        "",
        "> Automatisch synchronisiert vom Schulmanager-Online.",
        "",
        ""
    ]

    # Fächer und Aufgaben innerhalb der Tile auslesen[cite: 8]
    tile_body = target_tile.find("div", class_="tile-body")
    if tile_body:
        for subject_block in tile_body.find_all("div", recursive=False):
            h4 = subject_block.find("h4")
            p = subject_block.find("p", class_="homework-paragraph")
            
            if h4:
                subject = h4.text.strip()
                task = p.text.strip() if p else "Keine Beschreibung"

                if "keine ha" in task.lower() or not task:
                    md_lines.append(f"### {subject}")
                    md_lines.append(f"- [x] *{subject}: Keine HA*")
                    md_lines.append("")
                    continue

                md_lines.append(f"### {subject}")
                for subtask in task.split('\n'):
                    subtask = subtask.strip()
                    if subtask:
                        md_lines.append(f"- [ ] {subtask} 📅 {iso_datum}")
                md_lines.append("")

    md_content = "\n".join(md_lines)

# Direkt lokal in den Vault schreiben
    target_dir = "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben"
    
    filename = f"{iso_datum}.md"
    file_path = os.path.join(target_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    filename = f"{iso_datum}.md"
    file_path = os.path.join(target_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[Sync] Hausaufgaben erfolgreich lokal gespeichert: {file_path}")

if __name__ == "__main__":
    parse_and_sync_locally()