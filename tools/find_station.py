# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : find_station.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 22.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Sucht Stationen in der DB-Library nach Namen.
# ------------------------------------------------------------------------------------------
#  Nutzung . . . : python tools/find_station.py Lahnstein
#                  python tools/find_station.py "Bad Ems West"
#                  python tools/find_station.py Niederlahnstein --add niederlahnstein
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
import argparse
import sys
from pathlib import Path

import tomllib
import tomli_w

from deutsche_bahn_api.station_helper import StationHelper

CONFIG_PATH = Path(__file__).parent.parent / "config" / "mystations.toml"

# ------------------------------------------------------------------------------
#  Konfig lesen und laden
# ------------------------------------------------------------------------------

def load_config() -> dict:
    """TOML-Config laden, leeres Skelett zurückgeben falls Datei fehlt."""
    if not CONFIG_PATH.exists():
        return {"stations": {}}
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))

# ------------------------------------------------------------------------------
#  Station speichern
# ------------------------------------------------------------------------------
def save_station(key: str, station) -> None:
    """Station unter gewähltem Key in die Config schreiben."""
    config = load_config()
    config.setdefault("stations", {})

    if key in config["stations"]:
        print(f"⚠️  Station-Key '{key}' existiert bereits — überschreibe.")

    config["stations"][key] = {
        "eva": station.EVA_NR,
        "name": station.NAME,
        "ds100": station.DS100,
        "verkehr": station.Verkehr,
        # Komma → Punkt für lat/lon (DB liefert deutsche Notation)
        "lat": float(station.Breite.replace(",", ".")),
        "lon": float(station.Laenge.replace(",", ".")),
        "note": "",
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_bytes(tomli_w.dumps(config).encode("utf-8"))
    print(f"✅ Gespeichert als '{key}' in {CONFIG_PATH}")

# ------------------------------------------------------------------------------
#  Main section
# ------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="DB-Stationen suchen und optional speichern")
    parser.add_argument("query", help="Stationsname (Substring-Match)")
    parser.add_argument(
        "--add",
        metavar="KEY",
        help="Wenn nur EIN Treffer: unter diesem Key in mystations.toml speichern",
    )
    args = parser.parse_args()

    helper = StationHelper()
    helper.load_stations()

    results = helper.find_stations_by_name(args.query)

    if not results:
        print(f"Keine Station gefunden für: {args.query}")
        return 1

    print(f"\n{len(results)} Treffer für '{args.query}':\n")
    for s in results[:15]:
        eva = getattr(s, "EVA_NR", "—")
        name = getattr(s, "NAME", "—")
        ds100 = getattr(s, "DS100", "—")
        verkehr = getattr(s, "Verkehr", "—")
        print(f"  EVA: {eva:>8}  |  {name:<30}  |  DS100: {ds100:<6}  |  {verkehr}")

    # Auto-save nur, wenn genau ein Treffer + --add übergeben
    if args.add:
        if len(results) != 1:
            print(f"\n⚠️  --add benötigt EXAKT einen Treffer (gefunden: {len(results)}).")
            print("   Verfeinere die Suchanfrage.")
            return 1
        save_station(args.add, results[0])

    return 0


if __name__ == "__main__":
    sys.exit(main())