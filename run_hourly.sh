#!/bin/bash
# Stuendlicher Lauf: Schulmanager scrapen, danach fehlende Eintraege in die
# Tagesnotiz schreiben. Der Export laeuft auch, wenn der Scraper fehlschlaegt,
# damit bereits vorhandene Datenbankeintraege trotzdem synchronisiert werden.

set -uo pipefail

cd "$(dirname "$0")" || exit 1

exec 9>".run_hourly.lock"
if ! flock -n 9; then
    echo "[run_hourly] $(date -Is) Ein anderer Lauf ist aktiv, ueberspringe."
    exit 0
fi

status=0

echo "[run_hourly] $(date -Is) Scraper starten"
if ! .venv/bin/python scraper.py; then
    status=1
fi

echo "[run_hourly] $(date -Is) Markdown-Export starten"
if ! .venv/bin/python markdown_export.py; then
    status=1
fi

echo "[run_hourly] $(date -Is) Ende (Status $status)"
exit "$status"
