#!/bin/bash
# ==========================================================================================
#  BartoAI / OpenClaw
# ==========================================================================================
#  Skill . . . . : dbticker
#  Datei . . . . : dbticker.sh
#  Autor . . . . : Bartosz Stryjewski
#  Geändert am . : 05.05.2026  — auf installierten Entry-Point umgestellt (pyproject.toml)
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Wrapper für dbticker.
#                  Führt den Ticker-Lauf als User 'barto' aus
#                  (venv, .env und state gehören barto, nicht clawdbot).
#
#                  Ruft den `dbticker`-Entry-Point aus der venv auf, der
#                  via pyproject.toml [project.scripts] erzeugt wird.
#
#  Modi:
#    dbticker.sh                              → alle aktiven Routen (systemd-Timer)
#    dbticker.sh run                          → dasselbe
#    dbticker.sh run --route hin-0628         → nur diese Route (BartoLink-Refresh)
#    dbticker.sh status                       → State-Files anzeigen
# ==========================================================================================

DBTICKER=/home/barto/developments/projects/dbticker/.venv/bin/dbticker
APP_DIR=/home/barto/developments/projects/dbticker

cd "$APP_DIR" || { echo "dbticker-Verzeichnis nicht gefunden" >&2; exit 1; }

# Ticker läuft immer als barto (venv + state gehören barto).
# Argumente werden 1:1 an den Entry-Point durchgereicht.
run_ticker() {
  if [ "$(id -un)" = "barto" ]; then
    $DBTICKER "$@"
  else
    sudo -u barto $DBTICKER "$@"
  fi
}

case "$1" in
  run|'')
    # Ersten Parameter ('run' oder leer) abschneiden, Rest durchreichen.
    # So funktioniert sowohl `dbticker.sh run` als auch
    # `dbticker.sh run --route hin-0628`.
    shift 2>/dev/null
    run_ticker "$@"
    ;;

  status)
    echo "=== dbticker State-Files ==="
    ls -la $APP_DIR/state/*.json 2>/dev/null || echo "  (leer)"
    ;;

  help)
    echo '{
  "available_commands": {
    "run":                       "Alle aktiven Routen pruefen (default)",
    "run --route <id>":          "Nur die genannte Route pruefen (manueller Refresh)",
    "status":                    "State-Files anzeigen",
    "help":                      "Diese Hilfe"
  }
}'
    ;;

  *)
    echo "Unbekannter Befehl: $1" >&2
    echo "Verfügbar: run [--route <id>], status, help" >&2
    exit 1
    ;;
esac