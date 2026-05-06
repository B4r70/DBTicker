# ==========================================================================
#  Projektname · src/cli/config_io.py
#  ----------------------------------------------------
#  Config-Read/Write-Helfer für routes.toml und mystations.toml.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
"""Read/Write-Helfer für routes.toml und mystations.toml.

Im Unterschied zur Stdlib-`tomllib` wird hier `tomlkit` verwendet — das
erhält Kommentare, Whitespace und die Reihenfolge von Schlüsseln beim
Round-Trip. Wichtig, weil die routes.toml viele erklärende Kommentare hat,
die der Wizard nicht zerschießen soll.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import tomlkit
from tomlkit import TOMLDocument, table, aot, comment, nl


# ------------------------------------------------------------------------------
#  Pfade
# ------------------------------------------------------------------------------

#  __file__ liegt unter src/cli/config_io.py — also dreimal .parent
#  um auf den Projekt-Root zu kommen (config_io.py → cli → src → root).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ROUTES_PATH = CONFIG_DIR / "routes.toml"
STATIONS_PATH = CONFIG_DIR / "mystations.toml"


# ------------------------------------------------------------------------------
#  Read
# ------------------------------------------------------------------------------

def load_routes_doc() -> TOMLDocument:
    """Lädt routes.toml als tomlkit-Document (mit Kommentaren intakt).

    Wirft FileNotFoundError, wenn die Datei nicht existiert. Für reines
    Lesen der Routen-Daten in main.py reicht weiterhin tomllib — diese
    Funktion ist nur für den Wizard gedacht.
    """
    if not ROUTES_PATH.exists():
        raise FileNotFoundError(f"routes.toml nicht gefunden unter: {ROUTES_PATH}")
    return tomlkit.parse(ROUTES_PATH.read_text(encoding="utf-8"))


def load_stations_doc() -> TOMLDocument:
    """Lädt mystations.toml als tomlkit-Document."""
    if not STATIONS_PATH.exists():
        # Wenn noch keine Stationen-Datei existiert, leeres Doc zurückgeben
        return tomlkit.document()
    return tomlkit.parse(STATIONS_PATH.read_text(encoding="utf-8"))


def get_known_station_keys() -> list[str]:
    """Gibt eine Liste aller Station-Keys aus mystations.toml zurück."""
    doc = load_stations_doc()
    stations = doc.get("stations", {})
    return list(stations.keys())


def get_existing_route_ids() -> list[str]:
    """Gibt alle bereits vergebenen Route-IDs zurück."""
    try:
        doc = load_routes_doc()
    except FileNotFoundError:
        return []
    routes = doc.get("routes", [])
    return [r.get("id", "") for r in routes if r.get("id")]


def find_route_by_id(route_id: str) -> dict | None:
    """Sucht eine Route per ID. Gibt das Route-Dict zurück oder None."""
    try:
        doc = load_routes_doc()
    except FileNotFoundError:
        return None
    for r in doc.get("routes", []):
        if r.get("id") == route_id:
            # tomlkit-Items sind dict-kompatibel, aber für Lesen reicht uns
            # eine Plain-Dict-Kopie
            return dict(r)
    return None


# ------------------------------------------------------------------------------
#  Backup
# ------------------------------------------------------------------------------

def backup_routes_file() -> Path | None:
    """Legt ein Backup der routes.toml an, bevor schreibend zugegriffen wird.

    Gibt den Pfad zur Backup-Datei zurück, oder None, wenn die Originaldatei
    noch nicht existiert (= erster Lauf).
    """
    if not ROUTES_PATH.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = ROUTES_PATH.with_suffix(f".toml.bak.{timestamp}")
    shutil.copy2(ROUTES_PATH, backup_path)
    return backup_path


# ------------------------------------------------------------------------------
#  Write
# ------------------------------------------------------------------------------

def write_routes_doc(doc: TOMLDocument) -> None:
    """Schreibt das tomlkit-Document zurück nach routes.toml.

    Erstellt das Verzeichnis, falls nötig. Macht KEIN Backup — das ist
    Aufgabe des Aufrufers (siehe backup_routes_file).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ROUTES_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")


def add_route_to_doc(doc: TOMLDocument, route_data: dict) -> None:
    """Fügt eine neue Route ans Ende des [[routes]]-Arrays an.

    Felder werden in einer stabilen, lesbaren Reihenfolge geschrieben.
    Felder, die NICHT in route_data vorkommen, werden weggelassen — der
    Lade-Code in main.py ergänzt sie zur Laufzeit aus ROUTE_DEFAULTS.
    """
    # AoT (Array of Tables) holen oder anlegen
    if "routes" not in doc:
        doc["routes"] = aot()

    # Cast: tomlkit gibt Item zurück, aber wir wissen, es ist ein AoT.
    # Ohne diese Annotation meckert Pylance, dass `Item` kein `append` hat.
    routes_aot: aot = doc["routes"]  # type: ignore[assignment]
    new_table = _build_route_table(route_data)
    routes_aot.append(new_table)


def replace_route_in_doc(doc: TOMLDocument, route_id: str, route_data: dict) -> bool:
    """Ersetzt eine bestehende Route. Gibt True zurück bei Erfolg, False
    wenn die ID nicht gefunden wurde.
    """
    routes_aot = doc.get("routes")
    if routes_aot is None:
        return False

    for idx, existing in enumerate(routes_aot):
        if existing.get("id") == route_id:
            routes_aot[idx] = _build_route_table(route_data)
            return True
    return False


def remove_route_from_doc(doc: TOMLDocument, route_id: str) -> bool:
    """Entfernt eine Route per ID. Gibt True zurück, wenn gelöscht."""
    routes_aot = doc.get("routes")
    if routes_aot is None:
        return False

    for idx, existing in enumerate(routes_aot):
        if existing.get("id") == route_id:
            del routes_aot[idx]
            return True
    return False


# ------------------------------------------------------------------------------
#  Internal: Schöne Tabellen-Formatierung
# ------------------------------------------------------------------------------

# Reihenfolge der Felder im Output. Felder, die nicht hier stehen, kommen
# am Ende. Diese Reihenfolge orientiert sich an deiner aktuellen routes.toml.
FIELD_ORDER = [
    # Identität
    "id", "label",
    # Strecke
    "from_station", "to_station", "via_station",
    # Fahrplan
    "scheduled_departure", "line", "active_days",
    # Check-Mechanik (selten gesetzt, weil Defaults greifen)
    "check_window_before_min", "check_window_after_min",
    "alert_threshold_min", "max_delay_tracking_min",
    # All-Clear-Fenster
    "all_clear_window_start_min", "all_clear_window_end_min",
    # Tagesablauf
    "my_departure_time", "my_departure_label", "delay_shifts_my_time",
    "arrival_destination", "arrival_offset_min",
]


def _build_route_table(route_data: dict):
    """Baut ein tomlkit-Table für eine Route mit stabiler Feld-Reihenfolge."""
    t = table()

    # Felder in definierter Reihenfolge schreiben
    for field in FIELD_ORDER:
        if field in route_data:
            t[field] = route_data[field]

    # Felder, die nicht in FIELD_ORDER stehen (Forward-Compat), ans Ende
    for field, value in route_data.items():
        if field not in FIELD_ORDER:
            t[field] = value

    return t