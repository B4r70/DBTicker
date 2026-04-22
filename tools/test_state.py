"""Testskript für die State-Maschine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from db_client import DBClient
from checker import check_route
from state import (
    RouteState,
    decide_notification,
    state_path_for,
)


client = DBClient()

print("── Schritt 1: Route prüfen ──")
result = check_route(
    client,
    route_id="hin-0631",
    route_label="🚆 Morgens: Bad Ems West → Niederlahnstein (06:31)",
    from_station_eva=8000702,
    scheduled_departure="06:31",
    line="RB23",
    direction_contains="Koblenz",
)
print(f"  Status: {result.status.value}, Verspätung: {result.delay_minutes} Min")

print("\n── Schritt 2: State laden ──")
state_path = state_path_for("hin-0631")
print(f"  Pfad: {state_path}")
prev_state = RouteState.load(state_path)
print(f"  Bisheriger State: {prev_state}")

print("\n── Schritt 3: Notification-Entscheidung ──")
decision = decide_notification(result, prev_state, alert_threshold_min=3)
print(f"  Notify?  {decision.should_notify}")
print(f"  Grund:   {decision.reason}")
print(f"  Neuer State: {decision.new_state}")

print("\n── Schritt 4: State speichern (simuliert) ──")
decision.new_state.save(state_path)
print(f"  Gespeichert: {state_path}")