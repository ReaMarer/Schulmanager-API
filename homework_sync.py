import json
import base64
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# === COUCHDB & OBSIDIAN CONFIGURATION ===
COUCHDB_URL = "http://localhost:5984" # Da es auf dem Server läuft, reicht localhost
DB_NAME = "orga_vault"  
USERNAME = "admin"
PASSWORD = "201110M.k"

# Pfad innerhalb von Obsidian (Exakt so wie in deiner DB hinterlegt)
OBSIDIAN_SUBFOLDER = "00 Meta/Hausaufgaben/" 
# ========================================

def parse_and_sync_to_couchdb():
    wochentage = {
        "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
        "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag",
        "Sunday": "Sonntag"
    }
    heute_eng = datetime.now().strftime("%A")
    heute_de = wochentage[heute_eng]
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

    # 1. Heutiges Datum im HTML suchen
    date_element = soup.find(lambda tag: tag.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'div'] and heutiges_ziel_datum in tag.text)

    if not date_element:
        print(f"[Sync] Keine Hausaufgaben für {heutiges_ziel_datum} gefunden. Breche ab.")
        return

    # 2. Markdown-Inhalt generieren
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

    for element in date_element.find_all_next():
        if element.name in ['h1', 'h2', 'h3', 'h5', 'div'] and any(tag in element.text for tag in wochentage.values()):
            if heutiges_ziel_datum not in element.text:
                break 

        if element.name == 'h4':
            subject = element.text.strip()
            task_parts = []  # <--- FEHLER 1 BEHOBEN (Zuweisung korrigiert)
            
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

            if "keine ha" in task.lower() or not task:
                # Trotzdem anzeigen, aber abgehakt
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

    # 3. CouchDB Dokumenten-Struktur vorbereiten
    filename = f"{iso_datum}.md"
    doc_id = f"{OBSIDIAN_SUBFOLDER}{filename}"
    
    encoded_data = base64.b64encode(md_content.encode('utf-8')).decode('utf-8')
    now_ms = int(datetime.now().timestamp() * 1000)

    payload = {
        "_id": doc_id,
        "type": "plain",      
        "data": encoded_data,
        "ctime": now_ms,
        "mtime": now_ms,
        "deleted": False
    }

    # 4. Prüfen, ob das Dokument bereits existiert (um die Revision zu erhalten)
    req_url = f"{COUCHDB_URL}/{DB_NAME}/{requests.utils.quote(doc_id)}"
    try:
        response = requests.get(req_url, auth=(USERNAME, PASSWORD))
        if response.status_code == 200:
            existing_doc = response.json()
            payload["_rev"] = existing_doc["_rev"]
            print("[Sync] Bestehende Notiz gefunden. Aktualisiere Dokument...")
        
        # 5. In CouchDB speichern
        put_response = requests.put(req_url, json=payload, auth=(USERNAME, PASSWORD))
        
        if put_response.status_code in [200, 201]:  # <--- FEHLER 2 BEHOBEN (Liste ergänzt)
            print(f"[Sync] Erfolg! '{filename}' im korrekten LiveSync-Format hochgeladen.")
        else:
            print(f"[Sync] Fehler beim Upload: {put_response.status_code}\n{put_response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"[Sync] Netzwerkfehler bei CouchDB-Verbindung: {e}")

if __name__ == "__main__":
    parse_and_sync_to_couchdb()