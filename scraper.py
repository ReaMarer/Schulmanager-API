import asyncio
from playwright.async_api import async_playwright

async def scrape_homework():
    async with async_playwright() as p:
        print("[Scraper] Starte Browser...")
        browser = await p.chromium.launch(headless=True) # Auf True setzen, falls das Fenster stört
        context = await browser.new_context()
        page = await context.new_page()

        print("[Scraper] Navigiere zur Login-Seite...")
        await page.goto("https://login.schulmanager-online.de/#/modules/classbook/homework/")
        await page.wait_for_load_state("networkidle")

        print("[Scraper] Logge ein...")
        await page.get_by_label("E-Mail-Adresse / Benutzername").fill("marlon.krouss@outlook.de")
        await page.get_by_label("Passwort").fill("201110M.k1")
        await page.get_by_role("button", name="Einloggen", exact=True).click()

        print("[Scraper] Warte auf das Laden der Hausaufgaben...")
        await page.wait_for_selector("h1:has-text('Hausaufgaben')")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000) 

        # Speichert das echte, unberührte HTML der Seite ab
        html_content = await page.content()
        with open("raw_homework.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        
        print("[Scraper] HTML erfolgreich in 'raw_homework.html' gespeichert.")
        await browser.close()
