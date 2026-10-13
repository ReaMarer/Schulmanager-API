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

    # Zielpfad definieren
    target_dir = "/home/marlon/orga_vault_temp/01 Meta/Hausaufgaben"
    os.makedirs(target_dir, exist_ok=True)
    filename = f"{iso_datum}.md"
    file_path = os.path.join(target_dir, filename)

    # Bestehende abgehakte Aufgaben einlesen (Merge-Logik)
    completed_tasks = set()
    if os.path.exists(file_path):
        print(('[Sync] Existierende Datei gefunden. Lese abgehakte Aufgaben aus...'))
        try:
            with open(file_path, "r", encoding="utf-8") as existing_file:
                for line in existing_file:
                    line = line.strip()
                    if line.startswith("- [x]"):
                        # Den reinen Text ohne Checkbox und Datums-Tags extrahieren
                        task_text = line[5:].split(" 📅")[0].strip()
                        completed_tasks.add(task_text)
        except Exception as e:
            print(f"[Sync] Warnung beim Einlesen der bestehenden Datei: {e}")

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

    # Markdown-Inhalt generieren mit Frontmatter für Dataview
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

    # Fächer und Aufgaben innerhalb der Tile auslesen
    tile_body = target_tile.find("div", class_="tile-body")
    if tile_body:
        for subject_block in tile_body.find_all("div", recursive=False):
            h4 = subject_block.find("h4")
            p = subject_block.find("p", class_="homework-paragraph")
            
            if h4:
                subject = h4.text.strip()
                task = p.text.strip() if p else "Keine Beschreibung"

                if "keine ha" in task.lower() or not task:
                    item_text = f"**{subject}**: Keine HA"
                    checkbox_status = "x" if item_text in completed_tasks else " "
                    md_lines.append(f"- [{checkbox_status}] {item_text} 📅 {iso_datum}")
                    continue

                for subtask in task.split('\n'):
                    subtask = subtask.strip()
                    if subtask:
                        # Fach und Aufgabe direkt in der Zeile kombinieren für perfekte Kompatibilität
                        item_text = f"**{subject}**: {subtask}"
                        checkbox_status = "x" if item_text in completed_tasks else " "
                        md_lines.append(f"- [{checkbox_status}] {item_text} 📅 {iso_datum}")
        
        md_lines.append("")

    md_content = "\n".join(md_lines)

    # Direkt lokal in den Vault schreiben
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[Sync] Hausaufgaben erfolgreich lokal gespeichert & gemerged: {file_path}")

if __name__ == "__main__":
    parse_and_sync_locally()