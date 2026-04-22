# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : logging_setup.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 22.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Zentrale Logging-Konfiguration.
#                  Stellt zwei Handler bereit:
#                    1. Stream → stdout/journalctl (für systemd)
#                    2. File   → log/dbticker-YYYYMMDD.log (für Debug/Audit)
#                  Rotation: eine Datei pro Tag. Dateien älter als 30 Tage
#                  werden beim Start automatisch gelöscht.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# ------------------------------------------------------------------------------------------
#  Konfigurationen
# ------------------------------------------------------------------------------------------

BERLIN = ZoneInfo("Europe/Berlin")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "log"
LOG_RETENTION_DAYS = 30

# ------------------------------------------------------------------------------------------
#  Cleanup für alte Logs
# ------------------------------------------------------------------------------------------

def _cleanup_old_logs() -> None:
    """Löscht Logdateien, die älter als LOG_RETENTION_DAYS sind.

    Wird beim Logging-Setup einmal aufgerufen. Fehler hier sind nicht
    fatal — im Zweifel lieber weiterlaufen als crashen.
    """
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)

    try:
        for log_file in LOG_DIR.glob("dbticker-*.log"):
            if log_file.stat().st_mtime < cutoff.timestamp():
                log_file.unlink()
    except OSError:
        # Log-Verzeichnis existiert nicht oder keine Schreibrechte — ignorieren
        pass

# ------------------------------------------------------------------------------------------
#  Datenklassen
# ------------------------------------------------------------------------------------------

class _BerlinFormatter(logging.Formatter):
    """Formatter, der Zeitstempel explizit in Europe/Berlin rendert.

    Standardmäßig nutzt Python die System-Zeitzone — die liegt auf dem Server
    aber in UTC. Mit diesem Formatter stimmen Log-Zeiten immer mit der Welt da
    draußen überein.
    """

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=BERLIN)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

# ------------------------------------------------------------------------------------------
#  Logging Konfiguration
# ------------------------------------------------------------------------------------------

def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Initialisiert Logging für die gesamte Applikation.

    Sollte EINMAL aus main.py aufgerufen werden, bevor andere Module
    anfangen zu loggen.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_old_logs()

    # Tagesdatei: dbticker-YYYYMMDD.log
    today_str = datetime.now(BERLIN).strftime("%Y%m%d")
    logfile = LOG_DIR / f"dbticker-{today_str}.log"

    # Gemeinsamer Formatter für beide Handler
    formatter = _BerlinFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler 1: stdout → systemd-journal
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    # Handler 2: Datei → dbticker-YYYYMMDD.log
    file_handler = logging.FileHandler(logfile, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # Datei bekommt ALLES, auch DEBUG

    # Root-Logger konfigurieren
    root = logging.getLogger()
    # Vorherige Handler entfernen (falls configure_logging mehrfach gerufen wird)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(logging.DEBUG)  # damit DEBUG zur Datei durchkommt
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    logger = logging.getLogger("dbticker")
    logger.info("Logging initialisiert: %s", logfile)
    return logger