#!/bin/bash
set -e

./venv/bin/python3 main.py >> cron.log 2>&1
cd /home/marlon/Schulmanager-API

python3 main.py

sudo mkdir -p "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"

sudo cp -r "/home/marlon/orga_vault_temp/00 Meta/Hausaufgaben/"* "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault/00 Meta/Hausaufgaben/"

sudo chown -R www-data:www-data "/home/marlon/docker/nextcloud/data/marlon/files/orga_vault"

sudo docker exec -i --user www-data nextcloud-app php occ files:scan marlon

echo "Erfolgreich Abgeschlossen"

