"""Tests für _classify_day(), _matches_any() und _to_berlin_date() in src/calendar_check.py.

Alle drei sind pure Funktionen — kein Netzwerk, kein Cache, kein .env nötig.
ICS-Inhalte werden als Strings direkt übergeben.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.calendar_check import (
    CalendarCheck,
    _classify_day,
    _matches_any,
    _to_berlin_date,
)

BERLIN = ZoneInfo("Europe/Berlin")
UTC = ZoneInfo("UTC")

TARGET = date(2026, 5, 21)  # Donnerstag


def ics(events: list[str]) -> str:
    """Baut minimale gültige ICS-Datei mit den übergebenen VEVENT-Blöcken."""
    body = "\n".join(events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\n{body}\nEND:VCALENDAR"


def vevent(summary: str, dtstart: str, dtend: str) -> str:
    return (
        "BEGIN:VEVENT\n"
        f"SUMMARY:{summary}\n"
        f"DTSTART;VALUE=DATE:{dtstart}\n"
        f"DTEND;VALUE=DATE:{dtend}\n"
        "END:VEVENT"
    )


def vevent_utc(summary: str, dtstart_utc: str, dtend_utc: str) -> str:
    """VEVENT mit tz-aware UTC-Datetimes statt DATE-Values."""
    return (
        "BEGIN:VEVENT\n"
        f"SUMMARY:{summary}\n"
        f"DTSTART:{dtstart_utc}\n"
        f"DTEND:{dtend_utc}\n"
        "END:VEVENT"
    )


# ── _matches_any ──────────────────────────────────────────────────────────────

class TestMatchesAny:
    def test_treffer_gibt_true(self):
        assert _matches_any("Büro Lahnstein", ["Büro Lahnstein"]) is True

    def test_kein_treffer_gibt_false(self):
        assert _matches_any("Urlaub", ["Büro Lahnstein", "Mobiles Arbeiten"]) is False

    def test_case_insensitive(self):
        assert _matches_any("BÜRO LAHNSTEIN", ["Büro Lahnstein"]) is True

    def test_substring_reicht(self):
        assert _matches_any("Büro Lahnstein (Schicht)", ["Büro Lahnstein"]) is True

    def test_leere_keywords_gibt_false(self):
        assert _matches_any("Büro", []) is False


# ── _to_berlin_date ───────────────────────────────────────────────────────────

class TestToBerlinDate:
    def test_date_gibt_sich_selbst_zurueck(self):
        d = date(2026, 5, 21)
        assert _to_berlin_date(d) == d

    def test_utc_datetime_wird_nach_berlin_umgerechnet(self):
        # 21.05.2026 22:00 UTC = 22.05.2026 00:00 Berlin (CEST = UTC+2)
        dt = datetime(2026, 5, 21, 22, 0, tzinfo=UTC)
        assert _to_berlin_date(dt) == date(2026, 5, 22)

    def test_naive_datetime_wird_als_berlin_behandelt(self):
        dt = datetime(2026, 5, 21, 10, 0)  # keine tzinfo
        assert _to_berlin_date(dt) == date(2026, 5, 21)

    def test_falscher_typ_wirft_type_error(self):
        with pytest.raises(TypeError):
            _to_berlin_date("2026-05-21")


# ── _classify_day ─────────────────────────────────────────────────────────────

class TestClassifyDay:
    def test_buero_event_am_zieldatum_gibt_office(self):
        text = ics([vevent("Büro Lahnstein", "20260521", "20260522")])
        result = _classify_day(text, TARGET)
        assert result.status == "office"

    def test_remote_event_am_zieldatum_gibt_remote(self):
        text = ics([vevent("Mobiles Arbeiten", "20260521", "20260522")])
        result = _classify_day(text, TARGET)
        assert result.status == "remote"

    def test_kein_event_am_zieldatum_gibt_unknown(self):
        text = ics([])
        result = _classify_day(text, TARGET)
        assert result.status == "unknown"

    def test_event_an_anderem_datum_gibt_unknown(self):
        text = ics([vevent("Büro Lahnstein", "20260522", "20260523")])
        result = _classify_day(text, TARGET)
        assert result.status == "unknown"

    def test_office_gewinnt_gegen_remote(self):
        text = ics([
            vevent("Mobiles Arbeiten", "20260521", "20260522"),
            vevent("Büro Lahnstein", "20260521", "20260522"),
        ])
        result = _classify_day(text, TARGET)
        assert result.status == "office"

    def test_mehrtaegiges_event_deckt_zieldatum_ab(self):
        # Event läuft 20.–22. Mai → gilt am 20. und 21., nicht am 22.
        text = ics([vevent("Büro Lahnstein", "20260520", "20260522")])
        result = _classify_day(text, TARGET)
        assert result.status == "office"

    def test_dtend_ist_exklusiv(self):
        # DTEND=21.05. bedeutet: bis 20.05. inklusive, 21.05. NICHT mehr
        text = ics([vevent("Büro Lahnstein", "20260520", "20260521")])
        result = _classify_day(text, TARGET)
        assert result.status == "unknown"

    def test_utc_event_wird_korrekt_nach_berlin_umgerechnet(self):
        # 20.05.2026 22:00Z = 21.05.2026 00:00 Berlin (CEST)
        # 21.05.2026 22:00Z = 22.05.2026 00:00 Berlin
        # → Event gilt am 21.05. in Berlin
        text = ics([vevent_utc("Büro Lahnstein", "20260520T220000Z", "20260521T220000Z")])
        result = _classify_day(text, TARGET)
        assert result.status == "office"

    def test_matched_summary_wird_zurueckgegeben(self):
        text = ics([vevent("Büro Lahnstein Schicht A", "20260521", "20260522")])
        result = _classify_day(text, TARGET)
        assert result.matched_summary == "Büro Lahnstein Schicht A"

    def test_unknown_hat_kein_matched_summary(self):
        text = ics([])
        result = _classify_day(text, TARGET)
        assert result.matched_summary is None
