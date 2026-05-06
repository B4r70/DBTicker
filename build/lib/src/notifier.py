# ==========================================================================
#  Projektname · src/notifier.py
#  ----------------------------------------------------
#  Benachrichtigungs-Manager: Sendet Alerts via Push
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from src.checker import RouteCheckResult, TrainStatus


# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

logger = logging.getLogger(__name__)
BERLIN = ZoneInfo("Europe/Berlin")

# Defaults — können via .env überschrieben werden
DEFAULT_BARTOLINK_URL = "http://127.0.0.1:8765"
HTTP_TIMEOUT_SECONDS = 10


# ------------------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------------------

def notify(
    result: RouteCheckResult,
    *,
    route_id: str,
    current_platform: Optional[str] = None,
) -> bool:
    """Schickt einen Trip-Event an BartoLink.

    BartoLink entscheidet selbst, ob ein sichtbarer Push raus geht — dbticker
    muss sich darum nicht kümmern. Das ist genau der Sinn der Aggregation.

    Args:
        result: RouteCheckResult vom Checker.
        route_id: dbticker-Route-ID (z.B. "hin-0631").
        current_platform: Aktuelles Gleis (kann sich gegen planned_platform
                          unterscheiden — Gleisänderung).

    Returns:
        True, wenn BartoLink das Event akzeptiert hat. False bei Netzwerk-/
        HTTP-Fehlern. dbticker-main.py nutzt das, um State erst zu speichern,
        wenn das Event auch wirklich raus war.
    """
    base_url = os.environ.get("BARTOLINK_URL", DEFAULT_BARTOLINK_URL).rstrip("/")
    token = os.environ.get("BARTOLINK_TOKEN")

    if not token:
        logger.error(
            "BARTOLINK_TOKEN fehlt im Environment — Event kann nicht gesendet werden."
        )
        return False

    payload = _build_payload(result, route_id=route_id, current_platform=current_platform)
    if payload is None:
        # _build_payload hat bereits geloggt warum
        return False

    url = f"{base_url}/trips/events"
    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error("Trip-Event an BartoLink fehlgeschlagen: %s", e)
        return False

    response_data = r.json()
    logger.info(
        "Trip-Event akzeptiert: trip_key=%s, event_type=%s, "
        "push_sent=%s, recipients=%d",
        response_data.get("trip_key"),
        response_data.get("event_type"),
        response_data.get("push_sent"),
        response_data.get("push_recipients", 0),
    )
    return True


# ------------------------------------------------------------------------------
#  Payload-Bauer
# ------------------------------------------------------------------------------

def _build_payload(
    result: RouteCheckResult,
    *,
    route_id: str,
    current_platform: Optional[str],
) -> Optional[dict]:
    """Baut das JSON-Payload für POST /trips/events.

    Returns None, wenn essenzielle Felder fehlen (dann kann/sollte nicht
    gesendet werden — BartoLink würde es eh ablehnen).
    """
    # train_number, line, planned_departure sind Pflicht für den Trip-Key
    if result.train_number is None:
        logger.warning(
            "[%s] Kein train_number im Result — Trip-Event kann nicht gebaut werden.",
            route_id,
        )
        return None
    if result.train_line is None:
        logger.warning("[%s] Kein train_line im Result — überspringe.", route_id)
        return None
    if result.planned_departure is None:
        logger.warning(
            "[%s] Kein planned_departure im Result — überspringe.", route_id
        )
        return None

    # Status-Mapping: TrainStatus → BartoLink-Literal
    status_map = {
        TrainStatus.ON_TIME: "on_time",
        TrainStatus.DELAYED: "delayed",
        TrainStatus.CANCELLED: "cancelled",
        TrainStatus.NOT_FOUND: "not_found",
    }
    status_str = status_map.get(result.status, "on_time")

    # Verspätung nur bei delayed-Status sinnvoll
    delay_min: Optional[int] = result.delay_minutes if result.status == TrainStatus.DELAYED else None

    # Datum aus planned_departure (nicht "heute" — der Zug könnte ja kurz
    # vor Mitternacht abfahren und der Check nach Mitternacht laufen)
    departure_date = result.planned_departure.astimezone(BERLIN).strftime("%Y-%m-%d")
    departure_time = result.planned_departure.astimezone(BERLIN).strftime("%H:%M")

    # Verspätungs-Grund als Message-Text (falls bekannt)
    message: Optional[str] = None
    if (
        result.delay_reason is not None
        and hasattr(result.delay_reason, "resolved")
        and result.delay_reason.resolved.is_known
    ):
        message = result.delay_reason.resolved.text

    payload: dict = {
        "train_number": str(result.train_number),
        "route_id": route_id,
        "departure_date": departure_date,

        "line": result.train_line,
        "direction": result.destination or "",
        "planned_departure": departure_time,

        "planned_platform": result.planned_platform,
        "current_platform": current_platform or result.planned_platform,

        "status": status_str,
        "delay_min": delay_min,
        "message": message,
    }
    # Pydantic-Validierung mag "" für direction nicht (max_length, aber min_length 0 ok)
    # — direction ist ggf. leer wenn destination None war. BartoLink akzeptiert das.

    return payload