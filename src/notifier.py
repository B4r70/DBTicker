# ==========================================================================
#  DBTicker · src/notifier.py
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

# Ab dieser Lücke zur nächsten Fahrt gehen wir von Ersatzverkehr aus.
# Der RB23-Takt liegt tagsüber bei ~30 Min; 20 Min sind schon auffällig.
LUECKE_FUER_ERSATZVERKEHR_MIN = 20


# ------------------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------------------

def notify(
    result: RouteCheckResult,
    *,
    route_id: str,
    current_platform: Optional[str] = None,
    event_intent: str = "regular",
    minutes_to_departure: Optional[int] = None,
) -> bool:
    """Schickt einen Trip-Event an BartoLink.

    BartoLink entscheidet selbst, ob ein sichtbarer Push raus geht — dbticker
    muss sich darum nicht kümmern. Das ist genau der Sinn der Aggregation.

    Args:
        result: RouteCheckResult vom Checker.
        route_id: dbticker-Route-ID (z.B. "hin-0631").
        current_platform: Aktuelles Gleis (kann sich gegen planned_platform
                          unterscheiden — Gleisänderung).
        event_intent: 'regular' | 'force_push' | 'silent_observation'.
                      'silent_observation' = reine Statistik-Beobachtung, kein
                      sichtbarer Push, kein trip_events-Eintrag in BartoLink.
        minutes_to_departure: Minuten bis zur planmäßigen Abfahrt zum
                              Messzeitpunkt. Negativer Wert = Messung nach
                              planmäßiger Abfahrt.

    Returns:
        True, wenn BartoLink das Event akzeptiert hat. False bei Netzwerk-/
        HTTP-Fehlern.
    """
    base_url = os.environ.get("BARTOLINK_URL", DEFAULT_BARTOLINK_URL).rstrip("/")
    token = os.environ.get("BARTOLINK_TOKEN")

    if not token:
        logger.error(
            "BARTOLINK_TOKEN fehlt im Environment — Event kann nicht gesendet werden."
        )
        return False

    payload = _build_payload(
        result,
        route_id=route_id,
        current_platform=current_platform,
        event_intent=event_intent,
    )
    if payload is None:
        # _build_payload hat bereits geloggt warum
        return False

    # minutes_to_departure ist eine reine Analyse-Größe; wird nur durchgereicht
    # und von BartoLink in trip_observations.minutes_to_departure abgelegt.
    payload["minutes_to_departure"] = minutes_to_departure

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
        "Trip-Event akzeptiert: trip_key=%s, event_type=%s, intent=%s, "
        "push_sent=%s, recipients=%d",
        response_data.get("trip_key"),
        response_data.get("event_type"),
        event_intent,
        response_data.get("push_sent"),
        response_data.get("push_recipients", 0),
    )
    return True



# ------------------------------------------------------------------------------
#  Meldung, wenn gar kein Zug fährt
# ------------------------------------------------------------------------------

def notify_no_train(
    result: RouteCheckResult,
    *,
    route_label: str,
    scheduled_departure: str,
    via_station_name: str,
) -> bool:
    """Meldet über /push, dass zur geplanten Zeit kein Zug fährt.

    Bewusst NICHT über /trips/events: Ein Trip-Event braucht eine Zugnummer für
    den trip_key, und die gibt es in diesem Fall per Definition nicht. Genau
    daran ist die Meldung bisher stillschweigend gescheitert — der Ticker hat
    wochenlang jeden Morgen 'not_found' erkannt und nichts davon gesendet.

    Args:
        result: Check-Ergebnis mit Status NOT_FOUND.
        route_label: Menschenlesbarer Routenname aus routes.toml.
        scheduled_departure: Die geplante Abfahrt "HH:MM", die nicht existiert.
        via_station_name: Zielrichtung, für den Meldungstext.

    Returns:
        True, wenn BartoLink den Push angenommen hat.
    """
    base_url = os.environ.get("BARTOLINK_URL", DEFAULT_BARTOLINK_URL).rstrip("/")
    token = os.environ.get("BARTOLINK_TOKEN")

    if not token:
        logger.error("BARTOLINK_TOKEN fehlt im Environment — Push nicht möglich.")
        return False

    titel, text, meta = build_no_train_message(
        result,
        route_label=route_label,
        scheduled_departure=scheduled_departure,
        via_station_name=via_station_name,
    )

    nutzlast = {
        "title": titel,
        "body": text,
        "source": "dbticker",
        "priority": 10,
        "meta": meta,
    }

    try:
        r = requests.post(
            f"{base_url}/push",
            json=nutzlast,
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        # 404 = kein Gerät registriert. Kein Grund für einen Stacktrace, aber
        # auch kein Erfolg — sonst würde der State gespeichert und die Meldung
        # nie nachgeholt.
        if r.status_code == 404:
            logger.warning("Push nicht zugestellt: keine aktiven Empfänger registriert.")
            return False
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error("Push an BartoLink fehlgeschlagen: %s", e)
        return False

    daten = r.json()
    logger.info(
        "Push gesendet (%s): %d Empfänger, %d fehlgeschlagen",
        titel, daten.get("sent_to", 0), daten.get("failed", 0),
    )
    return True


def build_no_train_message(
    result: RouteCheckResult,
    *,
    route_label: str,
    scheduled_departure: str,
    via_station_name: str,
) -> tuple[str, str, dict]:
    """Baut Titel, Text und Meta für die Kein-Zug-Meldung.

    Reine Funktion ohne I/O — deshalb direkt testbar.

    Returns:
        (titel, text, meta)
    """
    # Wie lange klafft die Lücke bis zur nächsten echten Fahrt? Genau da hinein
    # fallen die Ersatzbusse — die stehen in keiner Fahrplan-API, weil sie
    # keine EVA-Nummer haben.
    luecke_min: Optional[int] = None
    naechste = result.next_to_destination
    if naechste is not None:
        stunde, minute = (int(t) for t in scheduled_departure.split(":"))
        geplant = naechste.planned_departure.replace(
            hour=stunde, minute=minute, second=0, microsecond=0
        )
        luecke_min = int((naechste.planned_departure - geplant).total_seconds() / 60)

    # Ersatzverkehr ist wahrscheinlich, wenn gar nichts fährt oder die nächste
    # Fahrt deutlich später liegt als ein normaler Taktabstand.
    ersatzverkehr = result.likely_replacement_service or (
        luecke_min is not None and luecke_min >= LUECKE_FUER_ERSATZVERKEHR_MIN
    )

    titel = f"Kein Zug um {scheduled_departure}"
    teile = [f"{route_label}: Um {scheduled_departure} fährt kein Zug."]

    if naechste is not None:
        teile.append(
            f"Nächste Fahrt Richtung {via_station_name}: "
            f"{naechste.line or '?'} {naechste.train_number or '?'} um "
            f"{naechste.planned_departure.strftime('%H:%M')}"
            + (f" ({luecke_min} Min später)." if luecke_min else ".")
        )
    else:
        teile.append(
            f"Im geprüften Zeitfenster fährt überhaupt keiner Richtung "
            f"{via_station_name}."
        )

    if ersatzverkehr:
        titel = f"Ersatzverkehr? Kein Zug um {scheduled_departure}"
        teile.append(
            "Bei Schienenersatzverkehr fahren Busse, die nicht in den "
            "Fahrplandaten stehen — bitte Reiseauskunft prüfen."
        )

    text = " ".join(teile)

    meta = {
        "route_id": result.route_id,
        "status": result.status.value,
        "scheduled_departure": scheduled_departure,
        "likely_replacement_service": ersatzverkehr,
        "gap_minutes": luecke_min,
        "connections_in_window": result.connections_in_window,
    }

    return titel, text, meta

# ------------------------------------------------------------------------------
#  Payload-Bauer
# ------------------------------------------------------------------------------

def _build_payload(
    result: RouteCheckResult,
    *,
    route_id: str,
    current_platform: Optional[str],
    event_intent: str = "regular",
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
    delay_min: Optional[int] = (
        result.delay_minutes if result.status == TrainStatus.DELAYED else None
    )

    # Datum aus planned_departure (nicht "heute" — der Zug könnte ja kurz
    # vor Mitternacht abfahren und der Check nach Mitternacht laufen)
    departure_date = result.planned_departure.astimezone(BERLIN).strftime("%Y-%m-%d")
    departure_time = result.planned_departure.astimezone(BERLIN).strftime("%H:%M")

    # Verspätungs-Grund als Message-Text (falls bekannt)
    # Priorität: 1. messagecodes.toml-Text, 2. ext-Freitext der DB-API
    message: Optional[str] = None
    if result.delay_reason is not None:
        if result.delay_reason.resolved.is_known:
            message = result.delay_reason.resolved.text
        elif result.delay_reason.external_text:
            message = result.delay_reason.external_text

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
        "event_intent": event_intent,
    }
    # Pydantic-Validierung mag "" für direction nicht (max_length, aber min_length 0 ok)
    # — direction ist ggf. leer wenn destination None war. BartoLink akzeptiert das.

    return payload