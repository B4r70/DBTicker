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
from notifier import notify_via_openclaw
from state import RouteState, decide_notification, state_path_for
from agent_prompt import build_agent_prompt

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dbticker")


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


def is_in_check_window(route: dict, now: datetime) -> bool:
    hh, mm = route["scheduled_departure"].split(":")
    scheduled = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)

    before = scheduled - timedelta(minutes=route["check_window_before_min"])
    after = scheduled + timedelta(minutes=route["check_window_after_min"])

    return before <= now <= after

# ------------------------------------------------------------------------------
#  Pro-Route-Verarbeitung
# ------------------------------------------------------------------------------

def process_route(
    client: DBClient,
    route: dict,
    stations: dict[str, dict],
    now: datetime,
) -> None:
    """Eine einzelne Route durchprüfen und ggf. benachrichtigen."""
    route_id = route["id"]
    route_label = route["label"]

    # --- Station-Referenz auflösen ---
    from_key = route["from_station"]
    if from_key not in stations:
        logger.error("Route %s: Station-Key '%s' nicht in mystations.toml", route_id, from_key)
        return

    from_eva = stations[from_key]["eva"]

    # --- Check ausführen ---
    logger.info("[%s] Starte Check (EVA %d, Abfahrt %s, Linie %s)",
                route_id, from_eva, route["scheduled_departure"], route["line"])

    try:
        result = check_route(
            client,
            route_id=route_id,
            route_label=route_label,
            from_station_eva=from_eva,
            scheduled_departure=route["scheduled_departure"],
            line=route["line"],
            direction_contains=route["direction_contains"],
        )
    except Exception as e:
        logger.exception("[%s] Check fehlgeschlagen: %s", route_id, e)
        return

    logger.info("[%s] Status: %s, Verspätung: %d Min",
                route_id, result.status.value, result.delay_minutes)

    # --- State laden ---
    state_path = state_path_for(route_id, now)
    previous_state = RouteState.load(state_path)

    # --- Entscheidung ---
    decision = decide_notification(
        result,
        previous_state,
        alert_threshold_min=route["alert_threshold_min"],
    )

    logger.info("[%s] Entscheidung: notify=%s (%s)",
                route_id, decision.should_notify, decision.reason)

    # --- Notifier ggf. aufrufen ---
    if decision.should_notify:
        prompt = build_agent_prompt(result, decision.reason, route)
        success = notify_via_openclaw(prompt, name=f"dbticker-{route_id}")
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

        if not is_in_check_window(route, now):
            logger.debug("[%s] Außerhalb Check-Fenster.", route_id)
            continue

        active_count += 1
        process_route(client, route, stations, now)

    logger.info("Fertig. %d Routen aktiv geprüft.", active_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())