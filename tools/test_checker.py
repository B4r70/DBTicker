# ==========================================================================
#  Projektname · tools/test_checker.py
#  ----------------------------------------------------
#  Testet die Checker-Logik mit einem synthetischen RouteCheckResult.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  06.05.2026
# ==========================================================================
#
from dotenv import load_dotenv
load_dotenv()

from src.db_client import DBClient
from src.checker import check_route


client = DBClient()

print("── Route-Check: Bad Ems West → Koblenz (06:31) ──\n")

result = check_route(
    client,
    route_id="hin-0631",
    route_label="🚆 Morgens: Bad Ems West → Niederlahnstein (06:31)",
    from_station_eva=8000702,
    scheduled_departure="06:31",
    line="RB23",
    via_station_name="Koblenz",
)

print(f"  Status:     {result.status.value}")
print(f"  Zug:        {result.train_line} {result.train_number}")
print(f"  Ziel:       {result.destination}")
print(f"  Abfahrt:    soll {result.planned_departure}, "
      f"ist {result.actual_departure or '—'}")
print(f"  Verspätung: {result.delay_minutes} Min")
print(f"  Gleis:      {result.planned_platform}")
print(f"  Alert?      {'JA' if result.is_alert_worthy else 'nein'}")