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
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from messagecodes import MessageCode, lookup_code

import requests

# ------------------------------------------------------------------------------
#  Zeitformat-Helfer
# ------------------------------------------------------------------------------

def parse_db_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """DB-Timestamp 'YYMMDDHHMM' als TZ-aware Berlin-Zeit parsen.
    
    Gibt None zurück, wenn ts None oder leer ist.
    Wirft ValueError bei falsch formatierten Strings.
    """
    if not ts:
        return None
    naive = datetime.strptime(ts, "%y%m%d%H%M")
    return naive.replace(tzinfo=BERLIN)

# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

API_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"

logger = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

# ------------------------------------------------------------------------------
#  Datenklasse: Stop -> Geplanter Halt eines Zuges an einer Station
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
    arrival_messages: list["Message"] = field(default_factory=list)
    departure_messages: list["Message"] = field(default_factory=list)

    @property
    def destination(self) -> Optional[str]:
        """Letzte Station im geplanten Weg = Zielbahnhof."""
        return self.planned_path[-1] if self.planned_path else None

# ------------------------------------------------------------------------------------------
#  Datenklasse: Änderungen zu einem Zug
# ------------------------------------------------------------------------------------------
@dataclass
class Change:
    """Eine gemeldete Änderung zu einem Stop."""
    stop_id: str
    changed_arrival: Optional[datetime]
    changed_departure: Optional[datetime]
    arrival_cancelled: bool
    departure_cancelled: bool
    arrival_messages: list["Message"] = field(default_factory=list)
    departure_messages: list["Message"] = field(default_factory=list)

# ------------------------------------------------------------------------------
#  Datenklasse Message -> Störungsmeldungen der DB
# ------------------------------------------------------------------------------
@dataclass
class Message:
    """Eine strukturierte Störungsmeldung aus einem <m>-Element.

    Die DB-API liefert pro Stop-Event (ar/dp) keine oder mehrere <m>-Elemente.
    Wir reichen sie als Liste weiter und lassen den Konsumenten entscheiden,
    welche am relevantesten ist.
    """
    code: str                       # Raw-Code aus dem XML, z.B. "95"
    type: Optional[str] = None      # "h" (HIM), "q" (Quality), ...
    category: Optional[str] = None  # roher 'cat'-Wert aus dem XML
    timestamp: Optional[datetime] = None  # ts
    external_text: Optional[str] = None   # 'ext'-Attribut, wenn vorhanden

    @property
    def resolved(self) -> MessageCode:
        """Code-Lookup in messagecodes.toml."""
        return lookup_code(self.code)

# ------------------------------------------------------------------------------------------
#  Parsing der Messagecodes (<m>-Elemente)
# ------------------------------------------------------------------------------------------
def parse_message_elements(parent: Optional[ET.Element]) -> list[Message]:
    """Extrahiert alle <m>-Elemente aus einem <ar> oder <dp>.

    Args:
        parent: Das <ar>- oder <dp>-Element (oder None, dann leere Liste).

    Returns:
        Liste von Message-Objekten in Reihenfolge des XML-Dokuments.
    """
    if parent is None:
        return []

    messages: list[Message] = []
    for m in parent.findall("m"):
        ts_raw = m.get("ts")
        ts_parsed = None
        if ts_raw:
            try:
                ts_parsed = parse_db_timestamp(ts_raw)
            except ValueError:
                # Defensive: manchmal weicht das ts-Format minimal ab
                pass

        messages.append(Message(
            code=m.get("c", ""),
            type=m.get("t"),
            category=m.get("cat"),
            timestamp=ts_parsed,
            external_text=m.get("ext"),
        ))

    return messages

# ------------------------------------------------------------------------------------------
#  Hauptursachen für Zugverspätungen
# ------------------------------------------------------------------------------------------
def primary_reason(messages: list[Message]) -> Optional[Message]:
    """Wählt aus einer Liste von Messages die 'beste' als Haupt-Grund.

    Heuristik:
      1. Bevorzugt bekannte Codes vor unbekannten
      2. Innerhalb der bekannten: höhere Severity schlägt niedrigere
      3. Bei Gleichstand: die erste im Dokument

    Returns:
        Die relevanteste Message oder None, falls Liste leer.
    """
    if not messages:
        return None

    severity_rank = {
        "critical": 4,
        "high":     3,
        "medium":   2,
        "low":      1,
        "unknown":  0,
    }

    def score(msg: Message) -> tuple[int, int]:
        resolved = msg.resolved
        is_known = 1 if resolved.is_known else 0
        sev = severity_rank.get(resolved.severity, 0)
        return (is_known, sev)

    return max(messages, key=score)

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

            if tl is None:
                continue

            ppth_source = dp if dp is not None else ar
            ppth = ppth_source.get("ppth", "") if ppth_source is not None else ""

            stops.append(Stop(
                stop_id=s.get("id", ""),
                line=(dp.get("l") if dp is not None else ar.get("l") if ar is not None else "") or "",
                train_category=tl.get("c", ""),
                train_number=tl.get("n", ""),
                planned_arrival=parse_db_timestamp(ar.get("pt")) if ar is not None else None,
                planned_departure=parse_db_timestamp(dp.get("pt")) if dp is not None else None,
                planned_platform=(dp.get("pp") if dp is not None else None),
                planned_path=ppth.split("|") if ppth else [],
                # NEU:
                arrival_messages=parse_message_elements(ar),
                departure_messages=parse_message_elements(dp),
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
                changed_arrival=parse_db_timestamp(ar.get("ct")) if ar is not None else None,
                changed_departure=parse_db_timestamp(dp.get("ct")) if dp is not None else None,
                arrival_cancelled=(ar is not None and ar.get("cs") == "c"),
                departure_cancelled=(dp is not None and dp.get("cs") == "c"),
                # NEU:
                arrival_messages=parse_message_elements(ar),
                departure_messages=parse_message_elements(dp),
            )

        return changes