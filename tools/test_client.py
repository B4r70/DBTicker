"""Testskript: den 06:31-Zug morgen an Bad Ems West finden."""
import sys
from pathlib import Path

# src importierbar machen
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from db_client import DBClient


client = DBClient()

# Morgen früh 06:xx an Bad Ems West
morgen = datetime.now() + timedelta(days=1)
morgen_06 = morgen.replace(hour=6, minute=0, second=0, microsecond=0)

print("── Soll-Fahrplan für Bad Ems West, 06:xx Uhr morgen ──")
plan = client.fetch_plan(eva=8000702, at=morgen_06)

for stop in plan:
    print(f"  {stop.line:<6} {stop.train_number:<6}  "
          f"ab {stop.planned_departure.strftime('%H:%M') if stop.planned_departure else '----'}  "
          f"Gl. {stop.planned_platform:<3}  "
          f"→ {stop.destination}")

print()
print("── Aktuelle Änderungen an Bad Ems West ──")
changes = client.fetch_changes(eva=8000702)
print(f"  {len(changes)} Züge mit Änderungen gemeldet")

# Den 06:31 herausfiltern
my_train = next(
    (s for s in plan if s.planned_departure and s.planned_departure.strftime("%H:%M") == "06:31"),
    None,
)

if my_train:
    print()
    print(f"── Dein Zug: {my_train.line} {my_train.train_number} ──")
    print(f"  Stop-ID: {my_train.stop_id}")
    print(f"  Ziel:    {my_train.destination}")

    if my_train.stop_id in changes:
        c = changes[my_train.stop_id]
        print(f"  ⚠️  Änderung gemeldet!")
        print(f"     Ist-Abfahrt: {c.changed_departure}")
    else:
        print("  ✅ Keine Änderung — fährt planmäßig.")