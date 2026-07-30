# ==========================================================================
#  Projektname · src/checker.py
#  ----------------------------------------------------
#  Prüft den Status einer Route anhand von Plan- und Change-Daten.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from enum import Enum

# Message und primary_reason mitnehmen:
from typing import Optional
from src.db_client import DBClient, Stop, Change, Message, primary_reason, parse_db_timestamp

# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

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
    delay_reason: Optional[Message] = None

    # Nur bei NOT_FOUND gesetzt — Kontext für die Meldung:
    # Der nächste Zug der Linie, der überhaupt zur Via-Station fährt.
    # None heißt: in diesem und im nächsten Stundenfenster fährt gar keiner.
    next_to_destination: Optional[Stop] = None
    # Wie viele Fahrten der Linie zur Via-Station im geprüften Fenster liegen.
    connections_in_window: int = 0

    @property
    def likely_replacement_service(self) -> bool:
        """Deutet der Befund auf Schienenersatzverkehr hin?

        Wenn die Route nicht gefunden wird und im geprüften Fenster gar keine
        Fahrt der Linie zum Ziel liegt, fährt dort schlicht kein Zug — der
        typische Fall bei Ersatzverkehr, denn Busse haben keine EVA-Nummer und
        tauchen in der Timetables-API überhaupt nicht auf.
        """
        return self.status == TrainStatus.NOT_FOUND and self.connections_in_window == 0
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

def find_connections(
    plan: list[Stop],
    *,
    line: str,
    via_station_name: str,
) -> list[Stop]:
    """Alle Abfahrten der Linie, die zur Via-Station führen — OHNE Zeitfilter.

    Kriterien:
      - Es gibt eine Abfahrt (Züge, die hier enden, haben keine)
      - Linie stimmt exakt
      - Geplanter Pfad enthält die Via-Station (substring-match,
        case-insensitive, damit 'Niederlahnstein' auch 'Niederlahnstein(Lahn)' matcht)

    Ohne den Zeitfilter lassen sich drei Fälle unterscheiden, die sonst alle
    als 'nicht gefunden' zusammenfallen: Fahrplan verschoben, gar keine
    Verbindung (→ Ersatzverkehr), oder Treffer.

    Returns:
        Nach geplanter Abfahrt sortierte Liste.
    """
    via_lower = via_station_name.lower()
    treffer = [
        stop for stop in plan
        if stop.planned_departure is not None
        and stop.line == line
        and any(via_lower in eintrag.lower() for eintrag in stop.planned_path)
    ]
    return sorted(treffer, key=lambda s: s.planned_departure)


def find_matching_train(
    plan: list[Stop],
    *,
    scheduled_departure: str,
    line: str,
    via_station_name: str,
) -> Optional[Stop]:
    """Sucht im Soll-Fahrplan den Zug, der zur Route passt.

    Wie find_connections(), zusätzlich mit exakter Abfahrtszeit (HH:MM).
    """
    for stop in find_connections(plan, line=line, via_station_name=via_station_name):
        if stop.planned_departure.strftime("%H:%M") == scheduled_departure:
            return stop

    return None

# ------------------------------------------------------------------------------------------
#  Delay Reasons
# ------------------------------------------------------------------------------------------

def _pick_delay_reason(train: Stop, change: Optional[Change]) -> Optional[Message]:
    """Sammelt alle <m>-Messages aus Plan und Changes und wählt die wichtigste.

    Zieht sowohl arrival- als auch departure-Messages heran und lässt
    primary_reason() nach Severity entscheiden.
    """
    all_messages: list[Message] = []

    # Plan-seitig (selten, aber möglich — z.B. bei HIM-Meldungen)
    all_messages.extend(train.arrival_messages)
    all_messages.extend(train.departure_messages)

    # Change-seitig (hier sind die echten Verspätungsgründe)
    if change is not None:
        all_messages.extend(change.arrival_messages)
        all_messages.extend(change.departure_messages)

    return primary_reason(all_messages)
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
        # Pünktlich, aber trotzdem könnten Plan-Messages da sein (selten)
        result.delay_reason = _pick_delay_reason(train, change=None)
        return result

    # --- Ausfall hat Vorrang vor Verspätung ---
    if change.departure_cancelled or change.arrival_cancelled:
        result.status = TrainStatus.CANCELLED
        result.delay_reason = _pick_delay_reason(train, change=change)
        return result

    # --- Verspätung berechnen ---
    if change.changed_departure is not None and train.planned_departure is not None:
        delay = (change.changed_departure - train.planned_departure).total_seconds() / 60
        result.delay_minutes = int(round(delay))
        result.actual_departure = change.changed_departure
        if result.delay_minutes > 0:
            result.status = TrainStatus.DELAYED
        else:
            result.status = TrainStatus.ON_TIME
            result.delay_minutes = max(0, result.delay_minutes)

    # --- Grund ermitteln (in allen Fällen, auch on_time mit Messages) ---
    result.delay_reason = _pick_delay_reason(train, change=change)

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
    via_station_name: str,
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
        via_station_name: z.B. "Niederlahnstein".

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
        via_station_name=via_station_name,
    )

    # Zug nicht gefunden. Bevor wir das als reines Problem melden: Fährt die
    # Linie hier überhaupt noch zum Ziel? Dafür die Folgestunde dazunehmen —
    # bei Ersatzverkehr klafft oft eine Lücke von ein bis zwei Stunden.
    # Der Extra-Call fällt nur in diesem Ausnahmefall an, nicht im Normalbetrieb.
    if train is None:
        fenster = list(plan)
        try:
            fenster += client.fetch_plan(
                eva=from_station_eva, at=target_time + timedelta(hours=1)
            )
        except Exception as e:
            logger.warning("Folgestunde für %s nicht abrufbar: %s", route_id, e)

        verbindungen = find_connections(
            fenster, line=line, via_station_name=via_station_name
        )
        naechste = next(
            (s for s in verbindungen if s.planned_departure >= target_time), None
        )

        logger.info(
            "[%s] Kein Zug um %s. Fahrten der Linie %s Richtung %s im Fenster: %d%s",
            route_id, scheduled_departure, line, via_station_name, len(verbindungen),
            f" (nächste {naechste.planned_departure.strftime('%H:%M')})" if naechste else "",
        )

        return RouteCheckResult(
            route_id=route_id,
            route_label=route_label,
            status=TrainStatus.NOT_FOUND,
            next_to_destination=naechste,
            connections_in_window=len(verbindungen),
        )

    # --- 3. Changes holen ---
    changes = client.fetch_changes(eva=from_station_eva)

    # --- 4. Status berechnen ---
    result = compute_status(train, changes)

    # Route-Metadaten einfügen (die kennt compute_status nicht)
    result.route_id = route_id
    result.route_label = route_label

    return result