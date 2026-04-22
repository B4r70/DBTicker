# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : messagecodes.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 22.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Lädt die Message-Code-Tabelle aus config/messagecodes.toml
#                  und bietet Lookup-Funktionen. Unbekannte Codes werden als
#                  sinnvoller Fallback aufbereitet, statt zu crashen.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ------------------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "messagecodes.toml"

# ------------------------------------------------------------------------------------------
#  Datenklassen
# ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MessageCode:
    """Eine übersetzte Message aus der DB-API."""
    code: str
    text: str
    category: str
    severity: str

    @property
    def is_known(self) -> bool:
        return self.category != "unknown"


class _Registry:
    """In-Memory-Cache der Codes. Lädt beim ersten Zugriff, dann gecached."""

    def __init__(self):
        self._codes: Optional[dict[str, dict]] = None

    def _load(self) -> dict[str, dict]:
        if self._codes is not None:
            return self._codes

        if not CONFIG_PATH.exists():
            logger.warning(
                "messagecodes.toml nicht gefunden bei %s — alle Codes werden als unbekannt markiert.",
                CONFIG_PATH,
            )
            self._codes = {}
            return self._codes

        try:
            data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            self._codes = data.get("codes", {})
            logger.debug("messagecodes geladen: %d Einträge", len(self._codes))
        except Exception as e:
            logger.error("messagecodes.toml defekt: %s — nutze leere Tabelle", e)
            self._codes = {}

        return self._codes

    def lookup(self, code: Optional[str]) -> MessageCode:
        """Übersetzt einen Message-Code in strukturierte Info.

        Bei unbekannten oder fehlenden Codes wird ein Fallback-Objekt mit
        category='unknown' zurückgegeben, damit aufrufender Code nicht mit
        None umgehen muss.
        """
        if not code:
            return MessageCode(
                code="",
                text="Keine Information",
                category="unknown",
                severity="unknown",
            )

        codes = self._load()
        entry = codes.get(str(code))

        if entry is None:
            return MessageCode(
                code=str(code),
                text=f"Code {code} (unbekannter Grund)",
                category="unknown",
                severity="unknown",
            )

        return MessageCode(
            code=str(code),
            text=entry.get("text", f"Code {code}"),
            category=entry.get("category", "unknown"),
            severity=entry.get("severity", "unknown"),
        )


# Singleton — einmal instanziieren, überall nutzen
_registry = _Registry()


def lookup_code(code: Optional[str]) -> MessageCode:
    """Public API: Message-Code nachschlagen."""
    return _registry.lookup(code)