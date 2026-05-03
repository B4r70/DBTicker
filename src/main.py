# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : main.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Entry Point für systemd-getriggerten Ticker-Lauf.
#                  Liest Config, filtert aktive Routen im Check-Fenster,
#                  ruft Checker → State → Notifier pro Route.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import logging
import sys
import tomllib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo   # stdlib ab Python 3.9

from pathlib import Path

from dotenv import load_dotenv

from checker import RouteCheckResult, TrainStatus, check_route
from db_client import DBClient
from state import RouteState, decide_notification, state_path_for
from agent_prompt import build_agent_prompt
from notifier import notify
from logging_setup import configure_logging

# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

WEEKDAY_MAP = ["mo", "tu", "we", "th", "fr", "sa", "su"]

BERLIN = ZoneInfo("Europe/Berlin")

# ------------------------------------------------------------------------------
#  Logging Setup (gibt alles an stdout → systemd fängt's via journal)
# ------------------------------------------------------------------------------

logger = configure_logging()

# ------------------------------------------------------------------------------
#  Config-Laden
# ------------------------------------------------------------------------------

def load_stations() -> dict[str, dict]:
    """mystations.toml laden und als Dict station_key → Felder zurückgeben."""
    path = CONFIG_DIR / "mystations.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data.get("stations", {})


def load_routes() -> list[dict]:
    """routes.toml laden und Routen als Liste zurückgeben."""
    path = CONFIG_DIR / "routes.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data.get("routes", [])


# ------------------------------------------------------------------------------
#  Fenster- und Tages-Filter
# ------------------------------------------------------------------------------

def is_route_active_today(route: dict, now: datetime) -> bool:
    """Ist die Route am heutigen Wochentag aktiv?"""
    today_key = WEEKDAY_MAP[now.weekday()]
    return today_key in route.get("active_days", [])


def is_in_check_window(
    route: dict,
    now: datetime,
    *,
    last_reported_delay_min: int = 0,
) -> bool:
    """Ist diese Route gerade im aktiven Check-Fenster?

    Das Fenster bleibt nach hinten offen, solange der Zug noch nicht
    abgefahren ist (basierend auf der zuletzt gemeldeten Verspätung).
    Ein konfigurierbarer Hard-Cap (`max_delay_tracking_min`) verhindert,
    dass der Ticker bei extremen Verspätungen oder unklaren Ausfällen
    endlos weiterprüft.
    """
    hh, mm = route["scheduled_departure"].split(":")
    scheduled = now.replace(
        hour=int(hh), minute=int(mm), second=0, microsecond=0
    )

    # Fenster-Start: feste Zeit vor geplanter Abfahrt
    window_start = scheduled - timedelta(minutes=route["check_window_before_min"])

    # Fenster-Ende: nimmt das Maximum aus
    #   - geplant + after_min  (Default-Verhalten)
    #   - ist + after_min      (verschiebt sich mit Verspätung)
    base_end = scheduled + timedelta(minutes=route["check_window_after_min"])
    if last_reported_delay_min > 0:
        delayed_end = base_end + timedelta(minutes=last_reported_delay_min)
        window_end = max(base_end, delayed_end)
    else:
        window_end = base_end

    # Hard-Cap: nie länger als max_delay_tracking_min nach geplanter Abfahrt
    cap = scheduled + timedelta(minutes=route.get("max_delay_tracking_min", 30))
    window_end = min(window_end, cap)

    return window_start <= now <= window_end


# ------------------------------------------------------------------------------
#  Pro-Route-Verarbeitung
# ------------------------------------------------------------------------------

def process_route(
    client: DBClient,
    route: dict,
    stations: dict[str, dict],
    now: datetime,
    *,
    previous_state: RouteState,
) -> None:
    """Eine einzelne Route durchprüfen und ggf. benachrichtigen."""
    route_id = route["id"]
    route_label = route["label"]

    # --- Station-Referenzen auflösen ---
    from_key = route["from_station"]
    if from_key not in stations:
        logger.error("Route %s: Station-Key '%s' nicht in mystations.toml", route_id, from_key)
        return
    from_eva = stations[from_key]["eva"]

    via_key = route["via_station"]
    if via_key not in stations:
        logger.error("Route %s: via_station-Key '%s' nicht in mystations.toml", route_id, via_key)
        return
    via_name = stations[via_key]["name"]

    # --- Check ausführen ---
    logger.info("[%s] Starte Check (EVA %d, Abfahrt %s, Linie %s)",
                route_id, from_eva, route["scheduled_departure"], route["line"])

    via_key = route["via_station"]
    if via_key not in stations:
        logger.error("Route %s: via_station-Key '%s' nicht in mystations.toml", route_id, via_key)
        return
    via_name = stations[via_key]["name"]

    try:
        result = check_route(
            client,
            route_id=route_id,
            route_label=route_label,
            from_station_eva=from_eva,
            scheduled_departure=route["scheduled_departure"],
            line=route["line"],
            via_station_name=via_name,
        )
    except Exception as e:
        logger.exception("[%s] Check fehlgeschlagen: %s", route_id, e)
        return

    logger.info("[%s] Status: %s, Verspätung: %d Min",
                route_id, result.status.value, result.delay_minutes)

    # --- State-Pfad für Speicherung (previous_state kommt als Parameter) ---
    state_path = state_path_for(route_id, now)

    # --- Entscheidung ---
    decision = decide_notification(
        result,
        previous_state,
        alert_threshold_min=route["alert_threshold_min"],
        all_clear_window_start_min=route.get("all_clear_window_start_min", 12),
        all_clear_window_end_min=route.get("all_clear_window_end_min", 8),
    )

    logger.info("[%s] Entscheidung: notify=%s (%s)",
                route_id, decision.should_notify, decision.reason)

    # --- Notifier ggf. aufrufen ---
    if decision.should_notify:
        # Agent-Prompt (für den Satz) bauen
        prompt = build_agent_prompt(result, decision.reason, route)

        # Station-Namen für das HTML-Template nachschlagen
        from_station_name = stations.get(route["from_station"], {}).get(
            "name", route["from_station"]
        )
        to_station_name = stations.get(route["to_station"], {}).get(
            "name", route["to_station"]
        )

        success = notify(
            result,
            agent_prompt=prompt,
            from_station_name=from_station_name,
            to_station_name=to_station_name,
        )

        if not success:
            # Bei Fehlschlag State NICHT mit notification_count+1 speichern,
            # damit beim nächsten Lauf nochmal versucht wird.
            logger.warning("[%s] Notify fehlgeschlagen — State nicht aktualisiert", route_id)
            return

    # --- State speichern ---
    decision.new_state.save(state_path)
    logger.debug("[%s] State gespeichert: %s", route_id, state_path)


# ------------------------------------------------------------------------------
#  Main
# ------------------------------------------------------------------------------

def main() -> int:
    load_dotenv()

    now = datetime.now(BERLIN)
    logger.info("DBTicker-Lauf gestartet: %s", now.isoformat(timespec="seconds"))

    # --- Config laden ---
    try:
        stations = load_stations()
        routes = load_routes()
    except Exception as e:
        logger.error("Config-Fehler: %s", e)
        return 1

    logger.info("Geladen: %d Stationen, %d Routen", len(stations), len(routes))

    # --- Client initialisieren ---
    try:
        client = DBClient()
    except KeyError as e:
        logger.error("API-Credentials fehlen: %s", e)
        return 1

    # --- Routen durchgehen ---
    active_count = 0
    for route in routes:
        route_id = route.get("id", "<unnamed>")

        if not is_route_active_today(route, now):
            logger.debug("[%s] Heute nicht aktiv (Wochentag).", route_id)
            continue

        # State laden, damit is_in_check_window die zuletzt gemeldete
        # Verspätung kennt und das Fenster ggf. nach hinten verschiebt.
        state_path = state_path_for(route_id, now)
        previous_state = RouteState.load(state_path)
        last_delay = previous_state.last_reported_delay or 0

        if not is_in_check_window(route, now, last_reported_delay_min=last_delay):
            logger.debug("[%s] Außerhalb Check-Fenster.", route_id)
            continue

        active_count += 1
        process_route(client, route, stations, now, previous_state=previous_state)

    logger.info("Fertig. %d Routen aktiv geprüft.", active_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())