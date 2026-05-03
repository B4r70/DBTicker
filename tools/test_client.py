"""Testskript: Plan an Bad Ems um 12:00 heute prüfen."""
import sys
from pathlib import Path

# src importierbar machen
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

from db_client import DBClient

BERLIN = ZoneInfo("Europe/Berlin")

# ── Erst Client erzeugen, DANN benutzen ──
client = DBClient()

heute_12 = datetime.now(BERLIN).replace(hour=12, minute=0, second=0, microsecond=0)

print("── Plan Bad Ems, 12:xx Uhr heute ──")
plan = client.fetch_plan(eva=8000701, at=heute_12)

for stop in plan:
    ab = stop.planned_departure.strftime('%H:%M') if stop.planned_departure else '----'
    print(f"  line={stop.line!r:<10} {stop.train_category}{stop.train_number:<6}  "
          f"ab {ab}  → {stop.destination}")