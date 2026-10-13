import json
import os
from datetime import datetime
from bs4 import BeautifulSoup

def parse_today_homework():
    wochentage = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag"
    }
    heute_eng = datetime.now().strftime("%A")
    heute_de = wochentage[heute_eng]
    datum_str = datetime.now().strftime("%d.%m.%Y")
    heutiges_ziel_datum = f"{heute_de}, {datum_str}"

    # Dynamischer Dateiname basierend auf dem aktuellen Datum
    json_filename = f"homework_{datum_str}.json"

    print(f"[Parser] Suche nach Hausaufgaben für: {heutiges_ziel_datum}")

    homework_data = {
        "date": heutiges_ziel_datum,
        "assignments": []
    }

    html_file = "raw_homework.html"

    try:
        with open(html_file, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except FileNotFoundError:
        print(f"[Parser] Fehler: '{html_file}' wurde nicht gefunden. Scraper prüfen!")
        return

    # 1. Überschrift des heutigen Tages finden
    date_element = soup.find(lambda tag: tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'div'] and heutiges_ziel_datum in tag.text)

    if not date_element:
        print(f"[Parser] Keine Einträge für das Datum '{heutiges_ziel_datum}' im HTML gefunden.")
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(homework_data, f, indent=4, ensure_ascii=False)
        
        # HTML-Datei trotzdem löschen, um den Ordner sauber zu halten
        if os.path.exists(html_file):
            os.remove(html_file)
        return

    # 2. Alle nachfolgenden Elemente chronologisch durchgehen
    for element in date_element.find_all_next():
        
        # Stop-Signal: Wenn ein anderes Datum beginnt
        if element.name in ['h1', 'h2', 'h3', 'h5', 'div'] and any(tag in element.text for tag in wochentage.values()):
            if heutiges_ziel_datum not in element.text:
                break 
        
        if element.name == 'h4':
            subject = element.text.strip()
            
            if any(a["subject"] == subject for a in homework_data["assignments"]):
                continue
                
            task_parts = []
            
            next_el = element.next_sibling
            while next_el and next_el.name != 'h4' and not (next_el.name in ['h1', 'h2', 'h3', 'h5', 'div'] and any(tag in next_el.text for tag in wochentage.values())):
                text = next_el.text.strip() if hasattr(next_el, 'text') else str(next_el).strip()
                if text and not text.startswith('<'): 
                    task_parts.append(text)
                next_el = next_el.next_sibling
            
            task = "\n".join(task_parts).strip()
            
            if not task and element.parent:
                parent_text = element.parent.text.replace(subject, "").strip()
                if parent_text:
                    task = parent_text

            homework_data["assignments"].append({
                "subject": subject,
                "task": task or "Keine Beschreibung"
            })

    # Speichern in die datumsabhängige JSON-Datei
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(homework_data, f, indent=4, ensure_ascii=False)
    
    print(f"[Parser] Filterung fertig! {len(homework_data['assignments'])} Fächer in '{json_filename}' gespeichert.")

    # 3. Temporäre HTML-Datei restlos löschen
    if os.path.exists(html_file):
        os.remove(html_file)
        print(f"[Parser] Bereinigung: '{html_file}' wurde erfolgreich gelöscht.")
