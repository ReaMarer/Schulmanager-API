#!/bin/bash
set -e

# 1. Zum Projektverzeichnis wechseln und Python-Skript starten
cd /home/marlon/Schulmanager-API
./venv/bin/python3 main.py >> cron.log 2>&1

# 2. Nextcloud Zielverzeichnis als Administrator (sudo) sicherstellen
sudo mkdir -p "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"

# 3. Aktuelles Datum ermitteln und NUR die heutige Datei sicher rüberschieben
HEUTE=$(date +%Y-%m-%d)
TEMP_FILE="/home/marlon/orga_vault_temp/00 Meta/Hausaufgaben/${HEUTE}.md"

if [ -f "$TEMP_FILE" ]; then
    sudo cp "$TEMP_FILE" "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"
fi

# 4. Rechte für Nextcloud-Webserver anpassen
sudo chown -R www-data:www-data "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault"

# 5. Nextcloud-Index aktualisieren
sudo docker exec -i --user www-data nextcloud-app php occ files:scan marlon

# 6. Lokalen Temp-Ordner aufräumen
rm -f /home/marlon/orga_vault_temp/00\ Meta/Hausaufgaben/*

echo "Erfolgreich Abgeschlossen"