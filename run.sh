#!/bin/bash
set -e

./venv/bin/python3 main.py >> cron.log 2>&1
cd /home/marlon/Schulmanager-API

python3 main.py

# Zielverzeichnis in Nextcloud sicherstellen
sudo mkdir -p "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"

# Aktuelles Datum im Format YYYY-MM-DD ermitteln (z.B. 2026-10-14)
HEUTE=$(date +%Y-%m-%d)
TEMP_FILE="/home/marlon/orga_vault_temp/00 Meta/Hausaufgaben/${HEUTE}.md"

# Nur die heutige Datei kopieren, falls sie existiert
if [ -f "$TEMP_FILE" ]; then
    sudo cp "$TEMP_FILE" "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"
fi

# Rechte für Nextcloud/Webserver anpassen
sudo chown -R www-data:www-data "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault"

# Nextcloud-Index aktualisieren
sudo docker exec -i --user www-data nextcloud-app php occ files:scan marlon

# Temporären Ordner bereinigen, damit alte Dateien gelöscht werden
rm -f /home/marlon/orga_vault_temp/00\ Meta/Hausaufgaben/*

echo "Erfolgreich Abgeschlossen"