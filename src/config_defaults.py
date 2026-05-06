# ==========================================================================
#  Projektname · src/config_defaults.py
#  ----------------------------------------------------
#  Default-Werte für Route-Konfigurationen.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
"""Zentrale Default-Werte für Route-Konfigurationen.

Felder, die hier definiert sind, müssen NICHT pro Route in routes.toml
gepflegt werden. Sie werden beim Laden der Routen automatisch aus diesen
Defaults ergänzt, falls in der TOML nicht gesetzt.

Pflicht-Felder (haben hier KEINEN Default und müssen pro Route gesetzt sein):
  id, label, from_station, to_station, via_station,
  scheduled_departure, line, active_days
"""


# ------------------------------------------------------------------------------
#  Defaults für Check-Mechanik
# ------------------------------------------------------------------------------
#  Diese Werte sind für eine typische S-/Regionalbahn-Pendlerroute sinnvoll
#  und müssen normalerweise nicht angepasst werden.

ROUTE_DEFAULTS: dict[str, object] = {
    # --- Check-Fenster ---
    "check_window_before_min": 35,   # Minuten vor Abfahrt: Start des Checks
    "check_window_after_min":  5,    # Minuten nach Abfahrt: Ende des Checks
    "max_delay_tracking_min":  30,   # Hard-Cap: nie länger als X Min nach Plan tracken

    # --- Alert-Logik ---
    "alert_threshold_min":     3,    # Ab wieviel Verspätung pingen?

    # --- All-Clear-Fenster (für 1× tägliche "Alles ok"-Meldung) ---
    "all_clear_window_start_min": 28,  # Min vor Abfahrt: Fenster-Start
    "all_clear_window_end_min":   24,  # Min vor Abfahrt: Fenster-Ende

    # --- Tagesablauf-Bezug (Push-Text-Kontext) ---
    "delay_shifts_my_time":  True,   # Verschiebt Verspätung deine Startzeit?
    "arrival_offset_min":    0,      # Minuten vom Zielbahnhof zum Endziel
}


# ------------------------------------------------------------------------------
#  Helfer
# ------------------------------------------------------------------------------

def apply_defaults(route: dict) -> dict:
    """Ergänzt fehlende Default-Felder in einem Route-Dict.

    Mutiert das Dict NICHT — gibt eine neue Kopie zurück. Felder, die in der
    Route bereits gesetzt sind (auch mit falsy-Werten wie 0 oder False),
    werden NICHT überschrieben.

    Beispiel:
        >>> route = {"id": "hin", "scheduled_departure": "06:31"}
        >>> apply_defaults(route)["alert_threshold_min"]
        3
        >>> apply_defaults(route)["scheduled_departure"]
        '06:31'
    """
    merged = {**ROUTE_DEFAULTS, **route}
    return merged


def is_default(field: str, value: object) -> bool:
    """True, wenn `value` dem Default für `field` entspricht.

    Wird von `route migrate` benutzt, um zu erkennen, welche Felder aus der
    TOML entfernt werden können, weil sie redundant sind.

    Felder, die nicht in ROUTE_DEFAULTS vorkommen (Pflicht-Felder), geben
    immer False zurück.
    """
    if field not in ROUTE_DEFAULTS:
        return False
    return ROUTE_DEFAULTS[field] == value