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

def is_lesson_cancelled(check_date_str, subject):
    """
    [ZUKUNFTS-ANSAATZ] Prüft, ob ein Fach an einem bestimmten Datum entfällt.
    Aktuell liest es optional eine 'entfall.json' aus (falls vorhanden) 
    und gibt standardmäßig False zurück, solange nichts eingetragen ist.
    """
    entfall_data = load_json_safely("entfall.json")
    if not entfall_data:
        return False
        
    # Prüfen, ob für das Datum Ausfälle eingetragen sind
    if check_date_str in entfall_data:
        ausgefallene_faecher = entfall_data[check_date_str]
        if subject in ausgefallene_faecher:
            print(f"[Entfall-Check] Fach '{subject}' fällt am {check_date_str} aus (Überspringe Termin).")
            return True
            
    return False

def get_next_lesson_date(current_date_obj, subject):
    """
    Ermittelt das Datum der nächsten Unterrichtsstunde basierend auf der stundenplan.json.
    Berücksichtigt das Fächer-Mapping und den Entfall-Mechanismus.
    """
    stundenplan = load_json_safely("stundenplan.json")
    if not stundenplan:
        print("[MarkdownWriter] Warnung: 'stundenplan.json' nicht gefunden. Verwende morgiges Datum als Fallback.")
        return current_date_obj + timedelta(days=1)

    # Mapping von Schulmanager-HTML-Namen auf deine stundenplan.json-Namen
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
    
    # Fach über das Mapping bereinigen, falls nötig
    mapped_subject = fach_mapping.get(subject, subject)

    wochentage_mapping = {
        0: "Montag", 1: "Dienstag", 2: "Mittwoch",
        3: "Donnerstag", 4: "Freitag", 5: "Samstag", 6: "Sonntag"
    }
    
    # Suche bis zu 21 Tage (3 Wochen) in die Zukunft
    for i in range(1, 22):
        check_date = current_date_obj + timedelta(days=i)
        check_date_str = check_date.strftime("%Y-%m-%d")
        check_weekday_index = check_date.weekday()
        
        # Wochenende überspringen (Samstag=5, Sonntag=6)
        if check_weekday_index >= 5:
            continue
            
        weekday_name = wochentage_mapping.get(check_weekday_index)
        
        # 1. Prüfen, ob das Fach überhaupt an diesem Wochentag laut Stundenplan stattfindet
        if weekday_name in stundenplan and mapped_subject in stundenplan[weekday_name]:
            
            # 2. [ZUKUNFTS-ANSAATZ] Hier greift die Entfall-Prüfung
            if is_lesson_cancelled(check_date_str, mapped_subject):
                continue # Überspringt diesen Tag und sucht den nächsten gültigen Termin
                
            return check_date

    # Fallback, falls das Fach in den nächsten 3 Wochen gar nicht auftaucht (oder alles ausfällt)
    return current_date_obj + timedelta(days=1)

def write_homework_markdown(iso_datum, heutiges_ziel_datum, target_tile):
    """
    Parst die Hausaufgaben aus der Tile, ermittelt das tatsächliche Abgabedatum 
    aus dem Stundenplan (inkl. Entfall-Vorbereitung) und schreibt sie in eine Markdown-Datei.
    Behält dabei bereits abgehakte Aufgaben (Merge-Logik) bei.
    """
    # Zielpfad auf dem Ubuntu-Server (Nextcloud / Vault)
    target_dir = "/home/marlon/orga_vault_temp/00 Meta/Hausaufgaben"
    os.makedirs(target_dir, exist_ok=True)
    filename = f"{iso_datum}.md"
    file_path = os.path.join(target_dir, filename)

    # Aktuelles Datum als datetime-Objekt für die Stundenplan-Berechnung
    current_date_obj = datetime.strptime(iso_datum, "%Y-%m-%d")

    # Bestehende abgehakte Aufgaben einlesen (Merge-Logik)
    completed_tasks = set()
    if os.path.exists(file_path):
        print('[MarkdownWriter] Existierende Datei gefunden. Lese abgehakte Aufgaben aus...')
        try:
            with open(file_path, "r", encoding="utf-8") as existing_file:
                for line in existing_file:
                    line = line.strip()
                    if line.startswith("- [x]"):
                        task_text = line[5:].split(" 📅")[0].strip()
                        completed_tasks.add(task_text)
        except Exception as e:
            print(f"[MarkdownWriter] Warnung beim Einlesen der bestehenden Datei: {e}")

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

                # Nächstes echtes Unterrichtsdatum (unter Berücksichtigung von Entfällen & Mapping) berechnen
                next_lesson_date = get_next_lesson_date(current_date_obj, subject)
                due_date_str = next_lesson_date.strftime("%Y-%m-%d")

                if "keine ha" in task.lower() or not task:
                    item_text = f"**{subject}**: Keine HA"
                    checkbox_status = "x" if item_text in completed_tasks else " "
                    md_lines.append(f"- [{checkbox_status}] {item_text} 📅 {due_date_str}")
                    continue

                for subtask in task.split('\n'):
                    subtask = subtask.strip()
                    if subtask:
                        item_text = f"**{subject}**: {subtask}"
                        checkbox_status = "x" if item_text in completed_tasks else " "
                        md_lines.append(f"- [{checkbox_status}] {item_text} 📅 {due_date_str}")
        
        md_lines.append("")

    md_content = "\n".join(md_lines)

    # Direkt lokal in den Vault schreiben
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"[MarkdownWriter] Hausaufgaben erfolgreich gespeichert: {file_path}")