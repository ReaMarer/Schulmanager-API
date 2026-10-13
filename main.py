import asyncio
import sys
import os
from scraper import scrape_homework
from homework_sync import parse_and_sync_to_couchdb

async def main():
    print("=== STARTING HOMEWORK SCRAPER & COUCHDB SYNC ===")
    
    # 1. Scraper ausführen
    try:
        await scrape_homework()
    except Exception as e:
        print(f"\n[FEHLER] Beim Scrapen ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        return

    print("\n-------------------------------------------")
    
    # 2. Parser & CouchDB Upload ausführen
    try:
        parse_and_sync_to_couchdb()
    except Exception as e:
        print(f"\n[FEHLER] Beim CouchDB-Sync ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        # Bei einem Fehler behalten wir das HTML zur Analyse ein
        return

    # 3. Zentrale Bereinigung der HTML-Datei nach erfolgreichem Upload
    if os.path.exists("raw_homework.html"):
        os.remove("raw_homework.html")
        print("[Main] Temporäre Datei 'raw_homework.html' erfolgreich bereinigt.")

    print("\n=== PROZESS ERFOLGREICH BEENDET ===")

if __name__ == "__main__":
    asyncio.run(main())
