"""Tests für _build_payload() in src/notifier.py.

_build_payload ist eine pure Transformation: RouteCheckResult → dict.
Kein Netzwerk, kein .env, kein I/O.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.checker import RouteCheckResult, TrainStatus
from src.notifier import _build_payload

BERLIN = ZoneInfo("Europe/Berlin")

DEPARTURE = datetime(2026, 5, 21, 6, 31, tzinfo=BERLIN)


def make_result(**kwargs) -> RouteCheckResult:
    defaults = dict(
        route_id="hin-0631",
        route_label="Test Route",
        status=TrainStatus.ON_TIME,
        train_number="12602",
        train_line="RB23",
        planned_departure=DEPARTURE,
        planned_platform="1",
    )
    defaults.update(kwargs)
    return RouteCheckResult(**defaults)


def build(**kwargs):
    result = kwargs.pop("result", make_result())
    return _build_payload(result, route_id=result.route_id, current_platform=None, **kwargs)


# ── Pflichtfeld-Validierung ────────────────────────────────────────────────────

class TestPflichtfelder:
    def test_kein_train_number_gibt_none(self):
        assert build(result=make_result(train_number=None)) is None

    def test_kein_train_line_gibt_none(self):
        assert build(result=make_result(train_line=None)) is None

    def test_kein_planned_departure_gibt_none(self):
        assert build(result=make_result(planned_departure=None)) is None

    def test_vollstaendiges_result_gibt_dict(self):
        assert build() is not None


# ── Status-Mapping ─────────────────────────────────────────────────────────────

class TestStatusMapping:
    @pytest.mark.parametrize("status,expected", [
        (TrainStatus.ON_TIME,   "on_time"),
        (TrainStatus.DELAYED,   "delayed"),
        (TrainStatus.CANCELLED, "cancelled"),
        (TrainStatus.NOT_FOUND, "not_found"),
    ])
    def test_status_wird_korrekt_gemappt(self, status, expected):
        payload = build(result=make_result(status=status))
        assert payload["status"] == expected


# ── Verspätungs-Felder ─────────────────────────────────────────────────────────

class TestDelayFields:
    def test_delay_min_bei_delayed_gesetzt(self):
        payload = build(result=make_result(status=TrainStatus.DELAYED, delay_minutes=7))
        assert payload["delay_min"] == 7

    def test_delay_min_bei_on_time_ist_none(self):
        payload = build(result=make_result(status=TrainStatus.ON_TIME, delay_minutes=0))
        assert payload["delay_min"] is None

    def test_delay_min_bei_cancelled_ist_none(self):
        payload = build(result=make_result(status=TrainStatus.CANCELLED))
        assert payload["delay_min"] is None


# ── Gleisfeld-Logik ────────────────────────────────────────────────────────────

class TestPlatformFelder:
    def test_current_platform_ueberschreibt_planned(self):
        result = make_result(planned_platform="1")
        payload = _build_payload(result, route_id=result.route_id, current_platform="3")
        assert payload["current_platform"] == "3"

    def test_current_platform_none_faellt_auf_planned_zurueck(self):
        result = make_result(planned_platform="2")
        payload = _build_payload(result, route_id=result.route_id, current_platform=None)
        assert payload["current_platform"] == "2"

    def test_planned_platform_wird_weitergegeben(self):
        payload = build(result=make_result(planned_platform="5"))
        assert payload["planned_platform"] == "5"


# ── Datums- und Zeitformatierung ───────────────────────────────────────────────

class TestDatumZeit:
    def test_departure_date_format_yyyy_mm_dd(self):
        payload = build()
        assert payload["departure_date"] == "2026-05-21"

    def test_departure_time_format_hh_mm(self):
        payload = build()
        assert payload["planned_departure"] == "06:31"


# ── Sonstige Felder ────────────────────────────────────────────────────────────

class TestSonstigeFelder:
    def test_route_id_wird_weitergegeben(self):
        payload = build()
        assert payload["route_id"] == "hin-0631"

    def test_train_number_ist_string(self):
        payload = build(result=make_result(train_number=12602))
        assert isinstance(payload["train_number"], str)
        assert payload["train_number"] == "12602"

    def test_direction_leer_wenn_destination_none(self):
        payload = build(result=make_result())
        # destination ist nicht gesetzt → dst=None → direction=""
        assert payload["direction"] == ""

    def test_event_intent_wird_durchgereicht(self):
        payload = _build_payload(
            make_result(),
            route_id="hin-0631",
            current_platform=None,
            event_intent="force_push",
        )
        assert payload["event_intent"] == "force_push"

    def test_message_none_wenn_kein_delay_reason(self):
        payload = build(result=make_result(delay_reason=None))
        assert payload["message"] is None
