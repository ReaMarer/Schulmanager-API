#!/bin/bash
set -e

# Zum Projektverzeichnis wechseln
cd /home/marlon/Schulmanager-API

# Python-Skript über die virtuelle Umgebung ausführen (schreibt direkt in den Vault)
./venv/bin/python3 main.py >> cron.log 2>&1

# Rechte für Nextcloud/Webserver anpassen
sudo chown -R www-data:www-data "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault"

# Nextcloud-Index aktualisieren, damit Obsidian/Nextcloud die Änderung sofort sehen
sudo docker exec -i --user www-data nextcloud-app php occ files:scan marlon

echo "Erfolgreich Abgeschlossen"