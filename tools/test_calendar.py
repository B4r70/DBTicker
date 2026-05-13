# ==========================================================================
#  DBTicker · tools/test_calendar.py
#  ----------------------------------------------------
#  Testskript für die Kalender-Abfrage.
#
#  Autor:  Bartosz Stryjewski
#  Datum:  13.05.2026
# ==========================================================================
#
"""Testskript für die Kalender-Abfrage.

Aufruf aus dem dbticker-Repo-Root:
    python tools/test_calendar.py

Erwartet CALENDAR_ICS_URL in .env oder als Umgebungsvariable.
"""
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

from src.calendar_check import (
    CACHE_FILE,
    _cache_age_minutes,
    get_status_for,
)


print("── Kalender-Check ──\n")

# Cache-Status vor dem ersten Call
age = _cache_age_minutes()
if age is None:
    print(f"  Cache:      nicht vorhanden ({CACHE_FILE})")
else:
    print(f"  Cache:      {age:.1f} Min alt ({CACHE_FILE})")

print()

# Heute + die nächsten 7 Tage durchgehen, damit man die mehrtägigen
# Block-Events sauber sieht.
today = date.today()
for offset in range(0, 8):
    d = today + timedelta(days=offset)
    weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][d.weekday()]
    result = get_status_for(d)

    # Status-Symbol für die Lesbarkeit
    symbol = {
        "office": "🏢",
        "remote": "🏠",
        "unknown": "❓",
    }[result.status]

    label = result.matched_summary or result.reason
    print(f"  {symbol} {weekday} {d.isoformat()}: {result.status:8s} — {label}")

print()

# Cache-Alter nach den Calls
age = _cache_age_minutes()
if age is not None:
    print(f"  Cache jetzt: {age:.2f} Min alt")

print("\nFertig.")
