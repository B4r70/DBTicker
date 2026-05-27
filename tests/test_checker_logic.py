"""Tests für find_matching_train() und compute_status() in src/checker.py.

Beide Funktionen sind pure — keine API-Calls, kein .env nötig.
Stop/Change werden synthetisch gebaut.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.db_client import Change, Stop
from src.checker import TrainStatus, compute_status, find_matching_train

BERLIN = ZoneInfo("Europe/Berlin")

PLAN_DEP = datetime(2026, 5, 21, 6, 31, tzinfo=BERLIN)


def make_stop(
    stop_id: str = "8000702-2606210631-1",
    line: str = "RB23",
    train_number: str = "12602",
    planned_departure: datetime | None = PLAN_DEP,
    planned_path: list[str] | None = None,
    planned_platform: str | None = "1",
) -> Stop:
    return Stop(
        stop_id=stop_id,
        line=line,
        train_category="RB",
        train_number=train_number,
        planned_arrival=None,
        planned_departure=planned_departure,
        planned_platform=planned_platform,
        planned_path=planned_path or ["Bad Ems West", "Niederlahnstein", "Koblenz Hbf"],
    )


def make_change(
    stop_id: str = "8000702-2606210631-1",
    changed_departure: datetime | None = None,
    departure_cancelled: bool = False,
    arrival_cancelled: bool = False,
) -> Change:
    return Change(
        stop_id=stop_id,
        changed_arrival=None,
        changed_departure=changed_departure,
        departure_cancelled=departure_cancelled,
        arrival_cancelled=arrival_cancelled,
    )


# ── find_matching_train ────────────────────────────────────────────────────────

class TestFindMatchingTrain:
    def test_exakter_treffer_wird_gefunden(self):
        stop = make_stop()
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is stop

    def test_falsche_abfahrtszeit_kein_treffer(self):
        stop = make_stop()
        result = find_matching_train(
            [stop],
            scheduled_departure="07:00",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is None

    def test_falsche_linie_kein_treffer(self):
        stop = make_stop()
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RE1",
            via_station_name="Niederlahnstein",
        )
        assert result is None

    def test_via_station_nicht_im_path_kein_treffer(self):
        stop = make_stop(planned_path=["Bad Ems West", "Koblenz Hbf"])
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is None

    def test_via_station_case_insensitive(self):
        stop = make_stop(planned_path=["Bad Ems West", "Niederlahnstein(Lahn)", "Koblenz Hbf"])
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="niederlahnstein",
        )
        assert result is stop

    def test_via_station_substring_match(self):
        stop = make_stop(planned_path=["Irgendwo", "Niederlahnstein(Lahn)", "Koblenz Hbf"])
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is stop

    def test_leerer_plan_gibt_none(self):
        result = find_matching_train(
            [],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is None

    def test_stop_ohne_planned_departure_wird_uebersprungen(self):
        stop = make_stop(planned_departure=None)
        result = find_matching_train(
            [stop],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is None

    def test_richtiger_zug_wird_aus_mehreren_herausgefunden(self):
        wrong1 = make_stop(stop_id="id-a", line="RE1")
        wrong2 = make_stop(stop_id="id-b", planned_departure=datetime(2026, 5, 21, 7, 0, tzinfo=BERLIN))
        correct = make_stop(stop_id="id-c")
        result = find_matching_train(
            [wrong1, wrong2, correct],
            scheduled_departure="06:31",
            line="RB23",
            via_station_name="Niederlahnstein",
        )
        assert result is correct


# ── compute_status ─────────────────────────────────────────────────────────────

class TestComputeStatus:
    def test_kein_change_ergibt_on_time(self):
        stop = make_stop()
        result = compute_status(stop, changes={})
        assert result.status == TrainStatus.ON_TIME
        assert result.delay_minutes == 0

    def test_departure_cancelled_ergibt_cancelled(self):
        stop = make_stop()
        change = make_change(stop_id=stop.stop_id, departure_cancelled=True)
        result = compute_status(stop, changes={stop.stop_id: change})
        assert result.status == TrainStatus.CANCELLED

    def test_arrival_cancelled_ergibt_cancelled(self):
        stop = make_stop()
        change = make_change(stop_id=stop.stop_id, arrival_cancelled=True)
        result = compute_status(stop, changes={stop.stop_id: change})
        assert result.status == TrainStatus.CANCELLED

    def test_verspaetete_abfahrt_ergibt_delayed(self):
        stop = make_stop()
        change = make_change(
            stop_id=stop.stop_id,
            changed_departure=PLAN_DEP + timedelta(minutes=7),
        )
        result = compute_status(stop, changes={stop.stop_id: change})
        assert result.status == TrainStatus.DELAYED
        assert result.delay_minutes == 7

    def test_delay_minutes_wird_korrekt_berechnet(self):
        stop = make_stop()
        change = make_change(
            stop_id=stop.stop_id,
            changed_departure=PLAN_DEP + timedelta(minutes=13),
        )
        result = compute_status(stop, changes={stop.stop_id: change})
        assert result.delay_minutes == 13

    def test_fruehzeitige_abfahrt_ergibt_on_time_mit_delay_null(self):
        # Frühzeitige Abfahrt (negativer Delay) → ON_TIME, delay=0
        stop = make_stop()
        change = make_change(
            stop_id=stop.stop_id,
            changed_departure=PLAN_DEP - timedelta(minutes=2),
        )
        result = compute_status(stop, changes={stop.stop_id: change})
        assert result.status == TrainStatus.ON_TIME
        assert result.delay_minutes == 0

    def test_kein_change_setzt_actual_departure_gleich_planned(self):
        stop = make_stop()
        result = compute_status(stop, changes={})
        assert result.actual_departure == PLAN_DEP

    def test_basisfelder_werden_vom_stop_uebernommen(self):
        stop = make_stop(line="RB23", train_number="12602", planned_platform="3")
        result = compute_status(stop, changes={})
        assert result.train_line == "RB23"
        assert result.train_number == "12602"
        assert result.planned_platform == "3"
