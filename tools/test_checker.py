import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from db_client import DBClient
from checker import check_route


client = DBClient()

print("── Route-Check: Bad Ems West → Koblenz (06:31) ──\n")

result = check_route(
    client,
    route_id="hin-0631",
    route_label="🚆 Morgens: Bad Ems West → Niederlahnstein (06:31)",
    from_station_eva=8000702,
    scheduled_departure="06:31",
    line="RB23",
    direction_contains="Koblenz",
)

print(f"  Status:     {result.status.value}")
print(f"  Zug:        {result.train_line} {result.train_number}")
print(f"  Ziel:       {result.destination}")
print(f"  Abfahrt:    soll {result.planned_departure}, "
      f"ist {result.actual_departure or '—'}")
print(f"  Verspätung: {result.delay_minutes} Min")
print(f"  Gleis:      {result.planned_platform}")
print(f"  Alert?      {'JA' if result.is_alert_worthy else 'nein'}")