# ==========================================================================
#  Projektname · src/cli/wizard.py
#  ----------------------------------------------------
#  Konfigurations-Wizard für das Anlegen und Bearbeiten von Routen.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
"""Interaktiver Wizard zum Anlegen/Bearbeiten von Routen.

Verwendet `questionary` für die Eingabe. Der Wizard kennt zwei Modi:
  - Neue Route:   prompt_route(initial=None)
  - Edit-Modus:   prompt_route(initial=existing_route_dict)

Im Edit-Modus werden die bestehenden Werte als Defaults vorbelegt, sodass
der User mit Enter durchsteppen kann und nur ändert, was er ändern will.
"""

from __future__ import annotations

import re

import questionary
from questionary import Choice
from src.config_defaults import ROUTE_DEFAULTS
from src.cli.config_io import get_known_station_keys, get_existing_route_ids

# ------------------------------------------------------------------------------
#  Validatoren
# ------------------------------------------------------------------------------

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

def _validate_time(text: str) -> bool | str:
    """questionary-Validator: erwartet "HH:MM" im 24-Stunden-Format."""
    if not text:
        return "Pflichtfeld."
    if not TIME_RE.match(text):
        return "Format: HH:MM (z.B. 06:31)"
    return True


def _validate_route_id(text: str, existing_ids: list[str], allow: str | None = None) -> bool | str:
    """ID muss URL-safe und eindeutig sein.

    `allow` ist die aktuelle ID im Edit-Modus — die darf erhalten bleiben.
    """
    if not text:
        return "Pflichtfeld."
    if not re.match(r"^[a-z0-9_-]+$", text):
        return "Nur Kleinbuchstaben, Ziffern, '-' und '_' erlaubt."
    if text in existing_ids and text != allow:
        return f"ID '{text}' ist bereits vergeben."
    return True


def _validate_int(text: str, min_val: int = 0, max_val: int = 999) -> bool | str:
    if not text:
        return "Pflichtfeld."
    try:
        n = int(text)
    except ValueError:
        return "Bitte eine ganze Zahl eingeben."
    if not (min_val <= n <= max_val):
        return f"Wert muss zwischen {min_val} und {max_val} liegen."
    return True


# ------------------------------------------------------------------------------
#  Hilfsfunktionen
# ------------------------------------------------------------------------------

def _suggest_route_id(scheduled_departure: str, label: str) -> str:
    """Schlägt eine ID basierend auf Uhrzeit + Richtungsindikator vor.

    Beispiel:  "06:31", "🚆 Morgens Bad Ems → Koblenz"
        →  "hin-0631"  (weil "Morgens" im Label)

    Heuristik ist bewusst simpel — User kann immer überschreiben.
    """
    hh, mm = scheduled_departure.split(":")
    label_lower = label.lower()

    if any(kw in label_lower for kw in ["morgen", "hin", "→ koblenz", "hinfahrt"]):
        prefix = "hin"
    elif any(kw in label_lower for kw in ["abend", "zurück", "zurueck", "rückfahrt", "rueckfahrt"]):
        prefix = "zurueck"
    else:
        prefix = "route"

    return f"{prefix}-{hh}{mm}"


WEEKDAYS = [
    ("mo", "Montag"),
    ("tu", "Dienstag"),
    ("we", "Mittwoch"),
    ("th", "Donnerstag"),
    ("fr", "Freitag"),
    ("sa", "Samstag"),
    ("su", "Sonntag"),
]


# ------------------------------------------------------------------------------
#  Haupt-Wizard
# ------------------------------------------------------------------------------

def prompt_route(initial: dict | None = None) -> dict | None:
    """Führt den User durch den Route-Anlage- oder Bearbeitungs-Dialog.

    Gibt das fertige Route-Dict zurück, oder None, wenn der User abgebrochen
    hat (Strg-C).

    Felder, die der User auf dem Default belassen hat, werden NICHT ins
    zurückgegebene Dict aufgenommen — so bleibt die routes.toml schlank.
    """
    is_edit = initial is not None
    initial = initial or {}
    existing_ids = get_existing_route_ids()
    known_stations = get_known_station_keys()

    if is_edit:
        questionary.print(f"\n✏️  Route '{initial.get('id')}' bearbeiten\n", style="bold")
    else:
        questionary.print("\n🚆 Neue DBTicker-Route anlegen\n", style="bold")

    try:
        # ----------------------------------------------------------------------
        # Block 1: Strecke
        # ----------------------------------------------------------------------

        from_station = _ask_station(
            "Von welcher Station fährst du ab?",
            known_stations,
            default=initial.get("from_station"),
        )
        if from_station is None:
            return None

        to_station = _ask_station(
            "Wohin fährt der Zug (Endbahnhof)?",
            known_stations,
            default=initial.get("to_station"),
        )
        if to_station is None:
            return None

        # via_station: Zug-Identifikation. Ist meist == to_station, kann aber
        # bei umsteigenden Routen abweichen. Default = to_station.
        via_station = _ask_station(
            "Über welche Station fährt der Zug zur Identifikation? (meist == Endbahnhof)",
            known_stations,
            default=initial.get("via_station") or to_station,
        )
        if via_station is None:
            return None

        # ----------------------------------------------------------------------
        # Block 2: Fahrplan
        # ----------------------------------------------------------------------

        scheduled_departure = questionary.text(
            "Planmäßige Abfahrt (HH:MM):",
            default=initial.get("scheduled_departure", ""),
            validate=_validate_time,
        ).ask()
        if scheduled_departure is None:
            return None

        line = questionary.text(
            "Welche Linie?",
            default=initial.get("line", "RB23"),
        ).ask()
        if line is None:
            return None

        active_days = _ask_active_days(initial.get("active_days"))
        if active_days is None:
            return None

        # ----------------------------------------------------------------------
        # Block 3: Identität
        # ----------------------------------------------------------------------

        suggested_label = initial.get("label") or f"🚆 {from_station} → {to_station}"
        label = questionary.text(
            "Beschreibung (für Push-Nachrichten):",
            default=suggested_label,
        ).ask()
        if label is None:
            return None

        suggested_id = initial.get("id") or _suggest_route_id(scheduled_departure, label)
        route_id = questionary.text(
            "Route-ID (für State-Files und Logs):",
            default=suggested_id,
            validate=lambda t: _validate_route_id(t, existing_ids, allow=initial.get("id")),
        ).ask()
        if route_id is None:
            return None

        # ----------------------------------------------------------------------
        # Block 4: Persönlicher Tagesablauf (optional)
        # ----------------------------------------------------------------------

        questionary.print(
            "\n─── Persönlicher Tagesablauf (optional) ───",
            style="fg:#888888",
        )

        want_routine = questionary.confirm(
            "Tagesablauf-Bezug konfigurieren? (für reichhaltigere Push-Texte)",
            default=bool(initial.get("my_departure_time")),
        ).ask()
        if want_routine is None:
            return None

        routine_fields: dict[str, object] = {}
        if want_routine:
            routine_result = _ask_routine(initial)
            if routine_result is None:
                return None
            routine_fields = routine_result

        # ----------------------------------------------------------------------
        # Block 5: Erweiterte Optionen
        # ----------------------------------------------------------------------

        questionary.print(
            "\n─── Erweiterte Optionen ───",
            style="fg:#888888",
        )

        _show_defaults()

        customize = questionary.confirm(
            "Defaults überschreiben? (sonst werden die Standard-Werte verwendet)",
            default=_has_custom_advanced(initial),
        ).ask()
        if customize is None:
            return None

        advanced_fields: dict[str, object] = {}
        if customize:
            advanced_result = _ask_advanced(initial)
            if advanced_result is None:
                return None
            advanced_fields = advanced_result

    except KeyboardInterrupt:
        questionary.print("\nAbgebrochen.", style="fg:#ff8888")
        return None

    # ----------------------------------------------------------------------
    # Zusammenbauen — nur Felder, die NICHT dem Default entsprechen
    # ----------------------------------------------------------------------

    result: dict = {
        "id": route_id,
        "label": label,
        "from_station": from_station,
        "to_station": to_station,
        "via_station": via_station,
        "scheduled_departure": scheduled_departure,
        "line": line,
        "active_days": active_days,
    }
    result.update(routine_fields)
    result.update(advanced_fields)

    return result


# ------------------------------------------------------------------------------
#  Sub-Dialoge
# ------------------------------------------------------------------------------

def _ask_station(prompt: str, known: list[str], default: str | None = None) -> str | None:
    """Frage nach Station-Key, mit Auto-Vervollständigung aus mystations.toml.

    Bietet auch Option 'Andere...' an für freie Eingabe (z.B. wenn die
    Station noch nicht in mystations.toml existiert — der Wizard warnt
    später, dass sie noch angelegt werden muss).
    """
    if not known:
        # mystations.toml ist leer → freie Eingabe
        return questionary.text(prompt, default=default or "").ask()

    choices = [Choice(title=key, value=key) for key in sorted(known)]
    choices.append(Choice(title="✏️  Andere... (manuell eingeben)", value="__other__"))

    selection = questionary.select(
        prompt,
        choices=choices,
        default=default if default in known else None,
    ).ask()

    if selection is None:
        return None
    if selection == "__other__":
        manual = questionary.text(
            "Station-Key (muss in mystations.toml angelegt werden):",
        ).ask()
        if manual:
            questionary.print(
                f"  ⚠ Achtung: Station '{manual}' ist noch nicht in mystations.toml.",
                style="fg:#ffaa00",
            )
            questionary.print(
                f"  → Lege sie an mit:  python tools/find_station.py \"<Name>\" --add {manual}",
                style="fg:#ffaa00",
            )
        return manual
    return selection


def _ask_active_days(initial: list[str] | None) -> list[str] | None:
    """Multi-Select für Wochentage. Default: alle Werktage."""
    initial = initial or ["mo", "tu", "we", "th", "fr"]

    choices = [
        Choice(title=name, value=key, checked=(key in initial))
        for key, name in WEEKDAYS
    ]
    selection = questionary.checkbox(
        "An welchen Wochentagen ist die Route aktiv?",
        choices=choices,
    ).ask()

    if selection is None:
        return None
    if not selection:
        questionary.print("⚠ Mindestens ein Wochentag muss ausgewählt sein.", style="fg:#ff8888")
        return _ask_active_days(initial)

    return selection


def _ask_routine(initial: dict) -> dict | None:
    """Sub-Dialog für die persönlichen Tagesablauf-Felder."""
    out: dict[str, object] = {}

    my_departure_time = questionary.text(
        "Wann startest du von zuhause / vom Büro? (HH:MM)",
        default=initial.get("my_departure_time", ""),
        validate=_validate_time,
    ).ask()
    if my_departure_time is None:
        return None
    out["my_departure_time"] = my_departure_time

    my_departure_label = questionary.text(
        "Was machst du dann? (z.B. 'mit dem E-Bike losfahren')",
        default=initial.get("my_departure_label", "losfahren"),
    ).ask()
    if my_departure_label is None:
        return None
    out["my_departure_label"] = my_departure_label

    delay_shifts = questionary.confirm(
        "Verschiebt eine Zugverspätung deine Startzeit?",
        default=initial.get("delay_shifts_my_time", ROUTE_DEFAULTS["delay_shifts_my_time"]),
    ).ask()
    if delay_shifts is None:
        return None
    # Nur speichern, wenn != Default
    if delay_shifts != ROUTE_DEFAULTS["delay_shifts_my_time"]:
        out["delay_shifts_my_time"] = delay_shifts

    arrival_destination = questionary.text(
        "Wo kommst du tatsächlich an? (z.B. 'prosozial', 'zu Hause')",
        default=initial.get("arrival_destination", ""),
    ).ask()
    if arrival_destination is None:
        return None
    if arrival_destination:  # leer ist OK → weglassen
        out["arrival_destination"] = arrival_destination

    arrival_offset = questionary.text(
        "Wieviele Minuten vom Zielbahnhof bis zum Endziel?",
        default=str(initial.get("arrival_offset_min", ROUTE_DEFAULTS["arrival_offset_min"])),
        validate=lambda t: _validate_int(t, 0, 120),
    ).ask()
    if arrival_offset is None:
        return None
    arrival_offset_int = int(arrival_offset)
    if arrival_offset_int != ROUTE_DEFAULTS["arrival_offset_min"]:
        out["arrival_offset_min"] = arrival_offset_int

    return out


def _ask_advanced(initial: dict) -> dict | None:
    """Sub-Dialog für die Mechanik-Felder. Wird nur aufgerufen, wenn der
    User explizit Defaults überschreiben möchte.

    Felder, die der User auf dem Default belässt, werden NICHT ins Output
    aufgenommen.
    """
    out: dict[str, object] = {}

    # Liste der Felder mit Beschreibung für die UI
    fields = [
        ("check_window_before_min", "Min vor Abfahrt: Check-Start", 5, 180),
        ("check_window_after_min",  "Min nach Abfahrt: Check-Ende", 0, 60),
        ("max_delay_tracking_min",  "Max-Tracking nach Plan-Abfahrt", 5, 240),
        ("alert_threshold_min",     "Alert-Schwelle (Min Verspätung)", 1, 60),
        ("all_clear_window_start_min", "All-Clear-Fenster Start (Min vor Abfahrt)", 1, 180),
        ("all_clear_window_end_min",   "All-Clear-Fenster Ende (Min vor Abfahrt)", 1, 180),
    ]

    for field, description, min_v, max_v in fields:
        default_val = initial.get(field, ROUTE_DEFAULTS[field])
        answer = questionary.text(
            f"{description}:  [Default: {ROUTE_DEFAULTS[field]}]",
            default=str(default_val),
            validate=lambda t, mn=min_v, mx=max_v: _validate_int(t, mn, mx),
        ).ask()
        if answer is None:
            return None
        answer_int = int(answer)
        if answer_int != ROUTE_DEFAULTS[field]:
            out[field] = answer_int

    return out


# ------------------------------------------------------------------------------
#  Anzeige-Helfer
# ------------------------------------------------------------------------------

def _show_defaults() -> None:
    """Zeigt die aktuell konfigurierten Defaults an."""
    questionary.print("Aktuelle Defaults:", style="fg:#888888")
    for key, value in ROUTE_DEFAULTS.items():
        questionary.print(f"  {key:32} = {value}", style="fg:#888888")


def _has_custom_advanced(route: dict) -> bool:
    """Prüft, ob die Route Mechanik-Felder mit Nicht-Default-Werten hat."""
    advanced_keys = [
        "check_window_before_min", "check_window_after_min",
        "max_delay_tracking_min", "alert_threshold_min",
        "all_clear_window_start_min", "all_clear_window_end_min",
    ]
    return any(
        key in route and route[key] != ROUTE_DEFAULTS[key]
        for key in advanced_keys
    )