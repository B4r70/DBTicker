"""Tests für decide_notification() in src/state.py.

Strategie: pure-function tests — kein I/O, kein Netzwerk, kein .env nötig.
Alle Cases aus der Entscheidungs-Logik werden durch öffentliche Interfaces
getestet (TrainStatus, RouteCheckResult, RouteState).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.checker import RouteCheckResult, TrainStatus
from src.state import RouteState, decide_notification

BERLIN = ZoneInfo("Europe/Berlin")
THRESHOLD = 5  # Minuten Alert-Schwelle für alle Tests


def make_result(
    status: TrainStatus,
    delay_minutes: int = 0,
    planned_platform: str | None = None,
    planned_departure: datetime | None = None,
) -> RouteCheckResult:
    return RouteCheckResult(
        route_id="test-route",
        route_label="Test Route",
        status=status,
        delay_minutes=delay_minutes,
        planned_platform=planned_platform,
        planned_departure=planned_departure,
    )


def make_state(**kwargs) -> RouteState:
    return RouteState(**kwargs)


# ── CANCELLED ──────────────────────────────────────────────────────────────────

class TestCancelled:
    def test_erste_meldung_loest_force_push_aus(self):
        d = decide_notification(
            make_result(TrainStatus.CANCELLED),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_erste_meldung_setzt_first_alert_at(self):
        d = decide_notification(
            make_result(TrainStatus.CANCELLED),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.new_state.first_alert_at is not None

    def test_bereits_als_cancelled_gemeldet_kein_push(self):
        d = decide_notification(
            make_result(TrainStatus.CANCELLED),
            make_state(last_reported_status="cancelled"),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False


# ── NOT_FOUND ──────────────────────────────────────────────────────────────────

class TestNotFound:
    def test_erste_meldung_loest_force_push_aus(self):
        d = decide_notification(
            make_result(TrainStatus.NOT_FOUND),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_bereits_gemeldet_kein_push(self):
        d = decide_notification(
            make_result(TrainStatus.NOT_FOUND),
            make_state(last_reported_status="not_found", notification_count=1),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False


# ── RECOVERY: pünktlich nach Verspätung ────────────────────────────────────────

class TestRecovery:
    def test_on_time_nach_delayed_loest_force_push_aus(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME),
            make_state(last_reported_status="delayed", last_reported_delay=7),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_new_state_hat_delay_null(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME),
            make_state(last_reported_status="delayed", last_reported_delay=7),
            alert_threshold_min=THRESHOLD,
        )
        assert d.new_state.last_reported_delay == 0


# ── ALL-CLEAR-FENSTER ──────────────────────────────────────────────────────────

class TestAllClear:
    def test_im_zeitfenster_loest_force_push_aus(self):
        # Abfahrt in 10 Min → mitten im 8–12-Min-Fenster
        departure = datetime.now(BERLIN) + timedelta(minutes=10)
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_departure=departure),
            make_state(notification_sent_today=False),
            alert_threshold_min=THRESHOLD,
            all_clear_window_start_min=12,
            all_clear_window_end_min=8,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_zu_frueh_kein_push(self):
        # Abfahrt in 30 Min → außerhalb des Fensters
        departure = datetime.now(BERLIN) + timedelta(minutes=30)
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_departure=departure),
            make_state(notification_sent_today=False),
            alert_threshold_min=THRESHOLD,
            all_clear_window_start_min=12,
            all_clear_window_end_min=8,
        )
        assert d.should_notify is False

    def test_bereits_heute_gesendet_kein_push(self):
        departure = datetime.now(BERLIN) + timedelta(minutes=10)
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_departure=departure),
            make_state(notification_sent_today=True),
            alert_threshold_min=THRESHOLD,
            all_clear_window_start_min=12,
            all_clear_window_end_min=8,
        )
        assert d.should_notify is False


# ── GLEISÄNDERUNG ──────────────────────────────────────────────────────────────

class TestPlatformChange:
    def test_gleisaenderung_loest_force_push_aus(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_platform="3"),
            make_state(last_reported_platform="1"),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_new_state_hat_neues_gleis(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_platform="3"),
            make_state(last_reported_platform="1"),
            alert_threshold_min=THRESHOLD,
        )
        assert d.new_state.last_reported_platform == "3"

    def test_gleiches_gleis_kein_push(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_platform="1"),
            make_state(last_reported_platform="1"),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False

    def test_kein_vorheriges_gleis_kein_wechsel_push(self):
        # prev_platform=None bedeutet: erster Check, kein "Wechsel" möglich
        d = decide_notification(
            make_result(TrainStatus.ON_TIME, planned_platform="3"),
            make_state(last_reported_platform=None),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False


# ── ON_TIME (kein Sonderfall) ──────────────────────────────────────────────────

class TestOnTime:
    def test_puenktlich_kein_push(self):
        d = decide_notification(
            make_result(TrainStatus.ON_TIME),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False


# ── DELAYED ────────────────────────────────────────────────────────────────────

class TestDelayed:
    def test_erstmeldung_unter_schwelle_kein_push(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=3),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False

    def test_erstmeldung_ueber_schwelle_loest_force_push_aus(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=7),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True
        assert d.intent == "force_push"

    def test_erstmeldung_setzt_first_alert_at(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=7),
            make_state(),
            alert_threshold_min=THRESHOLD,
        )
        assert d.new_state.first_alert_at is not None

    def test_folgemeldung_delta_unter_mindest_kein_push(self):
        # Delta = 1 Min < MIN_DELTA_FOR_REPING (2 Min)
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=7),
            make_state(last_reported_status="delayed", last_reported_delay=6),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is False

    def test_folgemeldung_delta_ueber_mindest_loest_push_aus(self):
        # Delta = 7 Min > MIN_DELTA_FOR_REPING (2 Min)
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=12),
            make_state(last_reported_status="delayed", last_reported_delay=5),
            alert_threshold_min=THRESHOLD,
        )
        assert d.should_notify is True

    def test_folgemeldung_aktualisiert_delay_im_state(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=12),
            make_state(last_reported_status="delayed", last_reported_delay=5),
            alert_threshold_min=THRESHOLD,
        )
        assert d.new_state.last_reported_delay == 12

    def test_folgemeldung_erhoehung_trend_up(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=12),
            make_state(last_reported_status="delayed", last_reported_delay=5),
            alert_threshold_min=THRESHOLD,
        )
        assert "↑" in d.reason

    def test_folgemeldung_verringerung_trend_down(self):
        d = decide_notification(
            make_result(TrainStatus.DELAYED, delay_minutes=5),
            make_state(last_reported_status="delayed", last_reported_delay=12),
            alert_threshold_min=THRESHOLD,
        )
        assert "↓" in d.reason
