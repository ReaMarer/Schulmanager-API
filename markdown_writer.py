import os
import json
from datetime import datetime, timedelta

def load_json_safely(filename):
    """Hilfsfunktion zum sicheren Laden von JSON-Dateien."""
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[MarkdownWriter] Warnung beim Laden von '{filename}': {e}")
        return None

def get_next_lesson_date(current_date_obj, subject):
    stundenplan = load_json_safely("stundenplan.json")
    if not stundenplan:
        return current_date_obj + timedelta(days=1)

    fach_mapping = {
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
        "Lateinisch, regulärer Beginn in Jahrgang 7": "Latein"
    }
    
    mapped_subject = fach_mapping.get(subject, subject)
    wochentage_mapping = {0: "Montag", 1: "Dienstag", 2: "Mittwoch", 3: "Donnerstag", 4: "Freitag", 5: "Samstag", 6: "Sonntag"}
    
    for i in range(1, 22):
        check_date = current_date_obj + timedelta(days=i)
        if check_date.weekday() >= 5:
            continue
        if mapped_subject in stundenplan.get(wochentage_mapping[check_date.weekday()], []):
            return check_date

    return current_date_obj + timedelta(days=1)

def write_homework_markdown(iso_datum, heutiges_ziel_datum, target_tile):
    # 1. Echter Nextcloud-Pfad zum Einlesen bereits abgehakter Aufgaben
    vault_dir = "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben"
    filename = f"{iso_datum}.md"
    vault_file_path = os.path.join(vault_dir, filename)

    # 2. Temporärer Pfad zum Erstellen der neuen Datei für den Kopiervorgang
    target_temp_dir = "/home/marlon/orga_vault_temp/00 Meta/Hausaufgaben"
    os.makedirs(target_temp_dir, exist_ok=True)
    temp_file_path = os.path.join(target_temp_dir, filename)

    current_date_obj = datetime.strptime(iso_datum, "%Y-%m-%d")

    # 3. Bestehende Aufgaben und deren Status robuster auslesen
    existing_task_status = {}
    if os.path.exists(vault_file_path):
        print('[MarkdownWriter] Existierende Datei im Vault gefunden. Lese Status ein...')
        try:
            with open(vault_file_path, "r", encoding="utf-8") as existing_file:
                for line in existing_file:
                    line = line.strip()
                    if line.startswith("- [") and "] " in line:
                        status = line[3:4] # 'x' oder ' '
                        # Extrahiere den reinen Text bis zum ersten Emoji (z. B. 📅)
                        task_part = line[5:]
                        for emoji in [" 📅", " ➕", " ⏫", " 🔽", " ⏳"]:
                            if emoji in task_part:
                                task_part = task_part.split(emoji)[0]
                        clean_task_content = task_part.strip()
                        existing_task_status[clean_task_content] = status
        except Exception as e:
            print(f"[MarkdownWriter] Warnung beim Einlesen: {e}")

    # 4. Aktuelle Aufgaben aus der Website-Kachel parsen
    new_tasks_found = []
    tile_body = target_tile.find("div", class_="tile-body")
    if tile_body:
        for subject_block in tile_body.find_all("div", recursive=False):
            h4 = subject_block.find("h4")
            p = subject_block.find("p", class_="homework-paragraph")
            
            if h4:
                subject = h4.text.strip()
                task = p.text.strip() if p else "Keine Beschreibung"
                next_lesson_date = get_next_lesson_date(current_date_obj, subject)
                due_date_str = next_lesson_date.strftime("%Y-%m-%d")

                if "keine ha" in task.lower() or not task:
                    item_text = f"**{subject}**: Keine HA"
                    new_tasks_found.append((item_text, due_date_str))
                    continue

                for subtask in task.split('\n'):
                    subtask = subtask.strip()
                    if subtask:
                        item_text = f"**{subject}**: {subtask}"
                        new_tasks_found.append((item_text, due_date_str))

    # 5. Smartes Zusammenführen mit Fallback auf exakten oder teilweisen Match
    final_task_lines = []
    for item_text, due_date_str in new_tasks_found:
        status = " "
        # Exakter Match oder Suche nach dem Fach-Präfix, falls sich der Text minimal geändert hat
        if item_text in existing_task_status:
            status = existing_task_status[item_text]
        else:
            # Fallback: Prüfen, ob der Aufgabentext (ohne Datum/Metadaten) schon mal da war
            for old_task, old_status in existing_task_status.items():
                if item_text == old_task:
                    status = old_status
                    break
        
        final_task_lines.append(f"- [{status}] {item_text} 📅 {due_date_str} ➕ {iso_datum} ⏫")

    # 6. Markdown-Inhalt zusammenbauen
    md_lines = [
        "---",
        f"date: {iso_datum}",
        f"last_updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "tags:",
        "  - schule",
        "  - hausaufgaben",
        "---",
        f"# 📚 Hausaufgaben für {heutiges_ziel_datum}",
    ] + final_task_lines + [""]

    md_content = "\n".join(md_lines)

    # 7. In die temporäre Datei schreiben
    with open(temp_file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[MarkdownWriter] Hausaufgaben intelligent aktualisiert: {temp_file_path}")