# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : checker.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Kernlogik für Route-Prüfung.
#                  Nimmt eine Route + DBClient, findet den passenden Zug
#                  im Soll-Fahrplan, vergleicht mit aktuellen Änderungen,
#                  gibt strukturierten Status zurück.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum
from typing import Optional

from db_client import DBClient, Stop, Change

# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

BERLIN = ZoneInfo("Europe/Berlin")

# ------------------------------------------------------------------------------
#  Datenklassen
# ------------------------------------------------------------------------------

class TrainStatus(str, Enum):
    """Möglicher Status eines überwachten Zuges."""
    ON_TIME = "on_time"          # Keine Verspätung gemeldet
    DELAYED = "delayed"          # Verspätung gemeldet
    CANCELLED = "cancelled"      # Ausfall gemeldet
    NOT_FOUND = "not_found"      # Zug nicht im Plan gefunden (Problem!)


@dataclass
class RouteCheckResult:
    """Ergebnis einer Route-Prüfung zu einem Zeitpunkt."""

    route_id: str
    route_label: str
    status: TrainStatus

    # Nur gesetzt wenn Zug gefunden:
    train_line: Optional[str] = None           # z.B. "RB23"
    train_number: Optional[str] = None         # z.B. "12602"
    destination: Optional[str] = None          # z.B. "Koblenz Hbf"
    planned_departure: Optional[datetime] = None
    actual_departure: Optional[datetime] = None
    delay_minutes: int = 0
    planned_platform: Optional[str] = None
    # ... weitere Felder später bei Bedarf

    @property
    def is_alert_worthy(self) -> bool:
        """Soll diese Route einen Alert auslösen?

        HINWEIS: Die Schwellen-Logik ('ab 3 Min') kommt später in state.py,
        weil dafür der letzte gemeldete Wert nötig ist. Hier nur:
        'gibt es überhaupt was zu berichten'.
        """
        return self.status in (TrainStatus.DELAYED, TrainStatus.CANCELLED, TrainStatus.NOT_FOUND)


# ------------------------------------------------------------------------------
#  Zug-Identifikation im Plan
# ------------------------------------------------------------------------------

def find_matching_train(
    plan: list[Stop],
    *,
    scheduled_departure: str,  # Format "HH:MM"
    line: str,
    direction_contains: str,
) -> Optional[Stop]:
    """Sucht im Soll-Fahrplan den Zug, der zur Route passt.

    Matching-Kriterien (alle müssen erfüllt sein):
      - Geplante Abfahrtszeit (HH:MM) stimmt exakt
      - Linie stimmt exakt
      - Zielrichtung enthält den konfigurierten Substring

    Args:
        plan: Liste aller Stops einer Stunde (von DBClient.fetch_plan).
        scheduled_departure: z.B. "06:31".
        line: z.B. "RB23".
        direction_contains: z.B. "Koblenz" (substring-match auf destination).

    Returns:
        Der passende Stop oder None.
    """
    for stop in plan:
        # Planned departure muss vorhanden sein
        if stop.planned_departure is None:
            continue

        # Exakte Abfahrtszeit prüfen
        if stop.planned_departure.strftime("%H:%M") != scheduled_departure:
            continue

        # Linie prüfen
        if stop.line != line:
            continue

        # Richtung prüfen (substring-match, weil Ziele wie "Koblenz Hbf" vs. "Koblenz Stadtmitte" existieren)
        destination = stop.destination or ""
        if direction_contains.lower() not in destination.lower():
            continue

        # Alle Kriterien erfüllt
        return stop

    return None

# ------------------------------------------------------------------------------
#  Status-Berechnung
# ------------------------------------------------------------------------------

def compute_status(train: Stop, changes: dict[str, Change]) -> RouteCheckResult:
    """Berechnet aus Plan-Stop + Changes-Dict den Status einer Route.

    Args:
        train: Der gefundene Soll-Zug aus dem Plan.
        changes: Das komplette Changes-Dict der Station.

    Returns:
        RouteCheckResult — aber ohne route_id/route_label, die setzt check_route().
    """
    # --- Basisfelder (immer gleich) ---
    result = RouteCheckResult(
        route_id="",                   # wird später überschrieben
        route_label="",                # wird später überschrieben
        status=TrainStatus.ON_TIME,    # Default, ggf. überschrieben
        train_line=train.line,
        train_number=train.train_number,
        destination=train.destination,
        planned_departure=train.planned_departure,
        planned_platform=train.planned_platform,
    )

    # --- Ist der Zug in den Changes? ---
    change = changes.get(train.stop_id)

    if change is None:
        # Kein Eintrag → keine Abweichung → pünktlich
        result.status = TrainStatus.ON_TIME
        result.actual_departure = train.planned_departure
        result.delay_minutes = 0
        return result

    # --- Ausfall hat Vorrang vor Verspätung ---
    if change.departure_cancelled or change.arrival_cancelled:
        result.status = TrainStatus.CANCELLED
        return result

    # --- Verspätung berechnen ---
    if change.changed_departure is not None and train.planned_departure is not None:
        delay = (change.changed_departure - train.planned_departure).total_seconds() / 60
        result.delay_minutes = int(round(delay))
        result.actual_departure = change.changed_departure

        # delay_minutes kann theoretisch negativ sein (Zug früher als geplant?) — 
        # behandeln wir als pünktlich, weil's praktisch nie vorkommt und
        # wenn doch, willst du keinen Alert.
        if result.delay_minutes > 0:
            result.status = TrainStatus.DELAYED
        else:
            result.status = TrainStatus.ON_TIME

    return result


# ------------------------------------------------------------------------------
#  Haupt-Einstiegspunkt für eine Route
# ------------------------------------------------------------------------------

def check_route(
    client: DBClient,
    *,
    route_id: str,
    route_label: str,
    from_station_eva: int,
    scheduled_departure: str,
    line: str,
    direction_contains: str,
) -> RouteCheckResult:
    """Vollständige Prüfung einer Route.

    Führt beide API-Calls aus, findet den Zug, berechnet Status.

    Args:
        client: Konfigurierter DBClient.
        route_id: z.B. "hin-0631" (für Logs/State).
        route_label: Menschenlesbare Beschreibung.
        from_station_eva: EVA-Nummer der Abfahrtsstation.
        scheduled_departure: Geplante Abfahrt "HH:MM".
        line: z.B. "RB23".
        direction_contains: z.B. "Koblenz".

    Returns:
        RouteCheckResult mit vollständigen Daten.
    """
    # Parse "HH:MM" in heute-Zeit, damit wir die richtige Stunde abrufen
    today = datetime.now(BERLIN)
    hour_str, minute_str = scheduled_departure.split(":")
    target_time = today.replace(
        hour=int(hour_str),
        minute=int(minute_str),
        second=0,
        microsecond=0,
    )

    # --- 1. Soll-Fahrplan holen ---
    plan = client.fetch_plan(eva=from_station_eva, at=target_time)

    # --- 2. Passenden Zug finden ---
    train = find_matching_train(
        plan,
        scheduled_departure=scheduled_departure,
        line=line,
        direction_contains=direction_contains,
    )

    # Zug nicht gefunden = Problem (andere Linie? Fahrplan geändert? Feiertag?)
    if train is None:
        return RouteCheckResult(
            route_id=route_id,
            route_label=route_label,
            status=TrainStatus.NOT_FOUND,
        )

    # --- 3. Changes holen ---
    changes = client.fetch_changes(eva=from_station_eva)

    # --- 4. Status berechnen ---
    result = compute_status(train, changes)

    # Route-Metadaten einfügen (die kennt compute_status nicht)
    result.route_id = route_id
    result.route_label = route_label

    return result