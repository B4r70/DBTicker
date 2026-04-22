#!/bin/bash
# ==========================================================================================
#  BartoAI / OpenClaw
# ==========================================================================================
#  Skill . . . . : dbticker
#  Datei . . . . : dbticker.sh
#  Autor . . . . : Bartosz Stryjewski
# ------------------------------------------------------------------------------------------
#  Beschreibung  : OpenClaw-Wrapper für dbticker.
#                  Führt den Ticker-Lauf als User 'barto' aus
#                  (venv, .env und state gehören barto, nicht clawdbot).
# ==========================================================================================
#
PYTHON=/home/barto/developments/projects/dbticker/.venv/bin/python
APP_DIR=/home/barto/developments/projects/dbticker
ENTRY=src/main.py

cd "$APP_DIR" || { echo "dbticker-Verzeichnis nicht gefunden" >&2; exit 1; }

# Ticker läuft immer als barto (venv + state gehören barto)
run_ticker() {
  if [ "$(id -un)" = "barto" ]; then
    $PYTHON $ENTRY
  else
    sudo -u barto $PYTHON $ENTRY
  fi
}

case "$1" in
  run|'')
    # Standard: einen Ticker-Lauf durchführen
    run_ticker
    ;;

  status)
    # Kompakte Übersicht: welche Routen sind aktiv, welcher State existiert
    echo "=== dbticker State-Files ==="
    ls -la $APP_DIR/state/*.json 2>/dev/null || echo "  (leer)"
    ;;

  help)
    echo '{
  "available_commands": {
    "run":    "Einen Ticker-Lauf durchführen (default)",
    "status": "State-Files anzeigen",
    "help":   "Diese Hilfe"
  }
}'
    ;;

  *)
    echo "Unbekannter Befehl: $1" >&2
    echo "Verfügbar: run, status, help" >&2
    exit 1
    ;;
esac
