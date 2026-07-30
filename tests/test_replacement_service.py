"""Tests für die Ersatzverkehr-Erkennung.

Strategie wie im übrigen Testordner: pure-function tests — kein I/O, kein
Netzwerk, kein .env nötig. Stops werden direkt konstruiert.

Hintergrund: Fällt eine Route wegen Schienenersatzverkehr aus, verschwindet
sie ersatzlos aus der Timetables-API — Busse haben keine EVA-Nummer. Ohne
find_connections() sieht der Ticker nur 'not_found' und kann nicht sagen, ob
der Fahrplan verschoben wurde oder gar nichts mehr fährt.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from src.checker import RouteCheckResult, TrainStatus, find_connections, find_matching_train
from src.db_client import Stop
from src.notifier import build_no_train_message

BERLIN = ZoneInfo("Europe/Berlin")


def stop(
    zeit: str | None,
    *,
    line: str = "RB23",
    nummer: str = "12602",
    pfad: list[str] | None = None,
) -> Stop:
    """Baut einen Halt. zeit=None → Zug endet hier (keine Weiterfahrt)."""
    abfahrt = None
    if zeit is not None:
        stunde, minute = (int(t) for t in zeit.split(":"))
        abfahrt = datetime(2026, 7, 31, stunde, minute, tzinfo=BERLIN)
    return Stop(
        stop_id=f"test-{nummer}-{zeit}",
        line=line,
        train_category="RB",
        train_number=nummer,
        planned_arrival=None,
        planned_departure=abfahrt,
        planned_platform="1",
        planned_path=pfad if pfad is not None else ["Niederlahnstein", "Koblenz Hbf"],
    )


def ergebnis(**kwargs) -> RouteCheckResult:
    return RouteCheckResult(
        route_id="hin-0628",
        route_label="Bad Ems → Niederlahnstein",
        status=TrainStatus.NOT_FOUND,
        **kwargs,
    )


# ------------------------------------------------------------------ find_connections

def test_findet_verbindungen_ohne_zeitbezug():
    plan = [stop("06:28"), stop("06:55", nummer="12692")]
    treffer = find_connections(plan, line="RB23", via_station_name="Niederlahnstein")
    assert [s.train_number for s in treffer] == ["12602", "12692"]


def test_sortiert_nach_abfahrt():
    plan = [stop("07:25", nummer="c"), stop("06:55", nummer="a"), stop("07:07", nummer="b")]
    treffer = find_connections(plan, line="RB23", via_station_name="Niederlahnstein")
    assert [s.train_number for s in treffer] == ["a", "b", "c"]


def test_ignoriert_zuege_die_hier_enden():
    """Ohne Abfahrt keine Weiterfahrt — bei Ersatzverkehr enden Züge am Bahnhof."""
    plan = [stop(None, nummer="12600"), stop("06:55", nummer="12692")]
    treffer = find_connections(plan, line="RB23", via_station_name="Niederlahnstein")
    assert [s.train_number for s in treffer] == ["12692"]


def test_ignoriert_andere_linie_und_richtung():
    plan = [
        stop("06:30", line="RE25"),
        stop("06:32", pfad=["Nassau(Lahn)", "Limburg(Lahn)"]),
    ]
    assert find_connections(plan, line="RB23", via_station_name="Niederlahnstein") == []


def test_via_station_matcht_als_teilstring():
    plan = [stop("06:55", pfad=["Niederlahnstein(Lahn)", "Koblenz Hbf"])]
    assert len(find_connections(plan, line="RB23", via_station_name="Niederlahnstein")) == 1


def test_matching_train_verlangt_exakte_zeit():
    plan = [stop("06:55", nummer="12692")]
    assert find_matching_train(
        plan, scheduled_departure="06:28", line="RB23", via_station_name="Niederlahnstein"
    ) is None
    assert find_matching_train(
        plan, scheduled_departure="06:55", line="RB23", via_station_name="Niederlahnstein"
    ) is not None


# ------------------------------------------------------------- likely_replacement_service

def test_ersatzverkehr_flag_nur_ohne_verbindung():
    assert ergebnis(connections_in_window=0).likely_replacement_service is True
    assert ergebnis(connections_in_window=4).likely_replacement_service is False


def test_flag_gilt_nur_bei_not_found():
    treffer = RouteCheckResult(
        route_id="x", route_label="y", status=TrainStatus.ON_TIME, connections_in_window=0
    )
    assert treffer.likely_replacement_service is False


# ------------------------------------------------------------- Meldungstext

def bau(**kwargs) -> tuple[str, str, dict]:
    return build_no_train_message(
        ergebnis(**kwargs),
        route_label="Bad Ems → Niederlahnstein",
        scheduled_departure="06:28",
        via_station_name="Niederlahnstein",
    )


def test_ohne_verbindung_weist_auf_ersatzverkehr_hin():
    titel, text, meta = bau(connections_in_window=0)
    assert "Ersatzverkehr" in titel
    assert "überhaupt keiner" in text
    assert meta["likely_replacement_service"] is True
    assert meta["gap_minutes"] is None


def test_grosse_luecke_gilt_als_ersatzverkehr():
    """Der reale Fall: 06:28 weg, nächster Zug erst 06:55."""
    titel, text, meta = bau(connections_in_window=4, next_to_destination=stop("06:55", nummer="12692"))
    assert "Ersatzverkehr" in titel
    assert "12692 um 06:55" in text
    assert "27 Min später" in text
    assert meta["gap_minutes"] == 27


def test_kleine_luecke_ist_nur_fahrplanaenderung():
    """Vier Minuten später ist eine Verschiebung, kein Ersatzverkehr."""
    titel, text, meta = bau(connections_in_window=4, next_to_destination=stop("06:32", nummer="12603"))
    assert "Ersatzverkehr" not in titel
    assert "Ersatzverkehr" not in text
    assert meta["gap_minutes"] == 4
    assert meta["likely_replacement_service"] is False


def test_meta_traegt_die_route():
    _, _, meta = bau(connections_in_window=0)
    assert meta["route_id"] == "hin-0628"
    assert meta["status"] == "not_found"
    assert meta["scheduled_departure"] == "06:28"
