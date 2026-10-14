import asyncio
import sys
import os
from scraper import scrape_homework
from homework_sync import parse_and_sync_locally

async def main():
    print("started reading homework.")
    
    try:
        await scrape_homework()
    except Exception as e:
        print(f"\n[FEHLER] Beim Scrapen ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        return
    
    # 2. Parser & Lokalen Export ausführen (ohne doppelten Funktionsaufruf)
    try:
        parse_and_sync_locally()
    except Exception as e:
        print(f"\n[FEHLER] Beim lokalen Speichern ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        return

    # 3. HTML-Datei nach erfolgreichem Speichern löschen
    if os.path.exists("raw_homework.html"):
        os.remove("raw_homework.html")
        print("[Main] Temporäre Datei 'raw_homework.html' erfolgreich bereinigt.")

    print("\n=== PROZESS ERFOLGREICH BEENDET ===")

if __name__ == "__main__":
    asyncio.run(main())