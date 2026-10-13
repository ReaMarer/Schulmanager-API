import asyncio
import sys
from scraper import scrape_homework
# Importiert jetzt fehlerfrei aus deiner umbenannten Datei
from homework_parser import parse_today_homework

async def main():
    print("=== STARTING HOMEWORK SCRAPER & PARSER ===")
    
    # 1. Scraper ausführen
    try:
        await scrape_homework()
    except Exception as e:
        print(f"\n[FEHLER] Beim Scrapen der Webseite ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        return

    print("\n-------------------------------------------")
    
    # 2. Parser ausführen
    try:
        parse_today_homework()
    except Exception as e:
        print(f"\n[FEHLER] Beim Parsen der HTML-Datei ist ein Fehler aufgetreten: {e}", file=sys.stderr)
        return

    print("\n=== PROZESS ERFOLGREICH BEENDET ===")

if __name__ == "__main__":
    asyncio.run(main())
