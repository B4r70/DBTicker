#!/usr/bin/env python3
# ==========================================================================
#  Projektname · tools/test_push.py
#  ----------------------------------------------------
#  Testet die Benachrichtigungs-Logik mit einem synthetischen RouteCheckResult.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
#!/usr/bin/env python3
# ===========================================================================================
#  Test: notifier.notify() — Trip-Event-Pipeline an BartoLink
# ===========================================================================================
#  Schickt einen synthetischen Trip-Event über die neue notify()-Funktion. Damit
#  testen wir die Pipeline (Payload-Bau, HTTP-Call, Bearer-Auth) unabhängig vom
#  echten Bahn-Datenfluss. BartoLink entscheidet dann selbst, ob ein sichtbarer
#  Push raus geht.
#
#  Ablauf:
#    1. Synthetisches RouteCheckResult (verspäteter RB23) bauen
#    2. Payload via _build_payload() erzeugen und als JSON anzeigen
#    3. Den User fragen, ob das Event wirklich an BartoLink geschickt werden soll
#    4. Bei Ja: notify() aufrufen, Response zeigen
# ===========================================================================================
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# .env aus dem Projekt-Root laden, BEVOR src.notifier importiert wird —
# der liest BARTOLINK_URL und BARTOLINK_TOKEN beim Aufruf aus os.environ.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.checker import RouteCheckResult, TrainStatus
from src.notifier import _build_payload, notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BERLIN = ZoneInfo("Europe/Berlin")


# ------------------------------------------------------------------------------
#  Synthetisches Test-Result
# ------------------------------------------------------------------------------

def build_test_result() -> RouteCheckResult:
    """Baut ein realistisches RouteCheckResult: verspäteter RB23, 7 Min später.

    Wichtig: planned_departure ist tz-aware (Europe/Berlin). Sonst kracht's
    in _build_payload beim astimezone().
    """
    return RouteCheckResult(
        route_id="hin-0631",
        route_label="🚆 Morgens Bad Ems → Koblenz",
        status=TrainStatus.DELAYED,
        train_line="RB23",
        train_number="12602",
        destination="Koblenz Hbf",
        planned_departure=datetime(2026, 5, 1, 6, 31, tzinfo=BERLIN),
        actual_departure=datetime(2026, 5, 1, 6, 38, tzinfo=BERLIN),
        planned_platform="1",
        delay_minutes=7,
        delay_reason=None,
    )


# ------------------------------------------------------------------------------
#  Hauptlogik
# ------------------------------------------------------------------------------

def main() -> int:
    result = build_test_result()

    # --- Schritt 1: Payload zeigen (Dry-Run) ---
    payload = _build_payload(
        result,
        route_id=result.route_id,
        current_platform="3",  # gleichzeitig Gleisänderung simulieren
    )

    if payload is None:
        print("❌ _build_payload hat None zurückgegeben — siehe Logs.")
        return 1

    print("─" * 70)
    print(" Trip-Event-Payload (das wird an BartoLink geschickt):")
    print("─" * 70)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("─" * 70)

    # --- Schritt 2: Bestätigung einholen ---
    answer = input(
        "\nWirklich an BartoLink senden? Das landet ggf. als echter Push "
        "auf deinem iPhone. [j/N] "
    ).strip().lower()

    if answer not in ("j", "ja", "y", "yes"):
        print("Abgebrochen — kein Event verschickt.")
        return 0

    # --- Schritt 3: Echt senden ---
    print("\nSende Trip-Event an BartoLink...")
    ok = notify(
        result,
        route_id=result.route_id,
        current_platform="3",
    )

    if ok:
        print("\n✓ Event akzeptiert. Details siehe Log-Zeile oben.")
        return 0
    else:
        print("\n❌ Event wurde NICHT akzeptiert. Mögliche Ursachen:")
        print("   - BARTOLINK_TOKEN fehlt oder ist falsch (.env prüfen)")
        print("   - BartoLink ist nicht erreichbar (Service down? URL falsch?)")
        print("   - HTTP-Error vom Server (siehe Log oben)")
        return 1


if __name__ == "__main__":
    sys.exit(main())