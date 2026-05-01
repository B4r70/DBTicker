#!/usr/bin/env python3
# ===========================================================================================
#  Test: notifier.send_to_barto_link()
# ===========================================================================================
#  Schickt einen synthetischen Push direkt über die neue Funktion. Damit
#  testen wir die Pipeline (Format-Bau, HTTP-Call, Auth) unabhängig vom
#  echten Bahn-Datenfluss.
# ===========================================================================================
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Damit src.* importierbar wird
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from checker import RouteCheckResult, TrainStatus
from notifier import build_push_payload, send_to_barto_link

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> int:
    # Synthetisches Result, das ein verspäteter RB23 wäre
    result = RouteCheckResult(
        route_id="hin-0631",
        route_label="Test",
        status=TrainStatus.DELAYED,
        train_line="RB23",
        destination="Koblenz Hbf",
        planned_departure=datetime(2026, 5, 1, 6, 31),
        actual_departure=datetime(2026, 5, 1, 6, 38),
        planned_platform="1",
        delay_minutes=7,
        delay_reason=None,
    )

    title, body = build_push_payload(
        result,
        agent_sentence="Du kannst 7 Min später losfahren.",
        from_station_name="Bad Ems West",
        to_station_name="Niederlahnstein",
    )

    print(f"--- Title ---\n{title}\n")
    print(f"--- Body ---\n{body}\n")

    print("Sende via barto-link...")
    ok = send_to_barto_link(title, body, source="dbticker.transit-test")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())