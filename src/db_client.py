# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : db_client.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : HTTP-Client für die DB Timetables API.
#                  Kapselt /plan, /fchg und das XML-Parsing.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import os
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import requests

# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

API_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

# ------------------------------------------------------------------------------
#  Datenklassen
# ------------------------------------------------------------------------------

@dataclass
class Stop:
    """Ein Halt eines Zuges an einer Station."""
    stop_id: str              # Eindeutig in Plan und Changes
    line: str                 # z.B. "RB23"
    train_category: str       # z.B. "RB", "ICE"
    train_number: str         # z.B. "12602"

    planned_arrival: Optional[datetime]    # pt aus <ar>
    planned_departure: Optional[datetime]  # pt aus <dp>
    planned_platform: Optional[str]        # pp aus <dp>
    planned_path: list[str]                # ppth, aufgesplittet

    @property
    def destination(self) -> Optional[str]:
        """Letzte Station im geplanten Weg = Zielbahnhof."""
        return self.planned_path[-1] if self.planned_path else None


@dataclass
class Change:
    """Eine gemeldete Änderung zu einem Stop."""
    stop_id: str
    changed_arrival: Optional[datetime]
    changed_departure: Optional[datetime]
    arrival_cancelled: bool
    departure_cancelled: bool


# ------------------------------------------------------------------------------
#  Zeitformat-Helfer
# ------------------------------------------------------------------------------

def parse_db_timestamp(ts: str) -> datetime:
    """DB-Timestamp 'YYMMDDHHMM' als TZ-aware Berlin-Zeit parsen."""
    naive = datetime.strptime(ts, "%y%m%d%H%M")
    return naive.replace(tzinfo=BERLIN)


# ------------------------------------------------------------------------------
#  API-Client
# ------------------------------------------------------------------------------

class DBClient:
    """Minimaler Wrapper um die DB Timetables API."""

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or os.environ["DB_API_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["DB_API_CLIENT_SECRET"]

    def _headers(self) -> dict:
        return {
            "DB-Client-Id": self.client_id,
            "DB-Api-Key": self.client_secret,
            "Accept": "application/xml",
        }

    def fetch_plan(self, eva: int, at: datetime) -> list[Stop]:
        date_str = at.strftime("%y%m%d")
        hour_str = at.strftime("%H")
        url = f"{API_BASE}/plan/{eva}/{date_str}/{hour_str}"

        logger.debug("fetch_plan: GET %s", url)

        r = requests.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()

        logger.debug(
            "fetch_plan response (status=%d, bytes=%d, ratelimit_remaining=%s):\n%s",
            r.status_code,
            len(r.text),
            r.headers.get("X-RateLimit-Remaining", "?"),
            r.text,
        )

        return self._parse_plan(r.text)

    def fetch_changes(self, eva: int) -> dict[str, Change]:
        url = f"{API_BASE}/fchg/{eva}"

        logger.debug("fetch_changes: GET %s", url)

        r = requests.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()

        logger.debug(
            "fetch_changes response (status=%d, bytes=%d, ratelimit_remaining=%s):\n%s",
            r.status_code,
            len(r.text),
            r.headers.get("X-RateLimit-Remaining", "?"),
            r.text,
        )

        return self._parse_changes(r.text)

    # --------------------------------------------------------------------------
    #  XML-Parsing (intern)
    # --------------------------------------------------------------------------

    @staticmethod
    def _parse_plan(xml_text: str) -> list[Stop]:
        root = ET.fromstring(xml_text)
        stops: list[Stop] = []

        for s in root.findall("s"):
            tl = s.find("tl")
            ar = s.find("ar")
            dp = s.find("dp")

            # Ohne tl-Element können wir den Zug nicht identifizieren
            if tl is None:
                continue

            # ppth immer aus <dp> ziehen (wenn vorhanden), sonst <ar>
            ppth_source = dp if dp is not None else ar
            ppth = ppth_source.get("ppth", "") if ppth_source is not None else ""

            stops.append(Stop(
                stop_id=s.get("id", ""),
                line=(dp.get("l") if dp is not None else ar.get("l") if ar is not None else "") or "",
                train_category=tl.get("c", ""),
                train_number=tl.get("n", ""),
                planned_arrival=parse_db_timestamp(ar.get("pt")) if ar is not None and ar.get("pt") else None,
                planned_departure=parse_db_timestamp(dp.get("pt")) if dp is not None and dp.get("pt") else None,
                planned_platform=(dp.get("pp") if dp is not None else None),
                planned_path=ppth.split("|") if ppth else [],
            ))

        return stops

    @staticmethod
    def _parse_changes(xml_text: str) -> dict[str, Change]:
        root = ET.fromstring(xml_text)
        changes: dict[str, Change] = {}

        for s in root.findall("s"):
            ar = s.find("ar")
            dp = s.find("dp")

            changes[s.get("id", "")] = Change(
                stop_id=s.get("id", ""),
                changed_arrival=parse_db_timestamp(ar.get("ct")) if ar is not None and ar.get("ct") else None,
                changed_departure=parse_db_timestamp(dp.get("ct")) if dp is not None and dp.get("ct") else None,
                arrival_cancelled=(ar is not None and ar.get("cs") == "c"),
                departure_cancelled=(dp is not None and dp.get("cs") == "c"),
            )

        return changes