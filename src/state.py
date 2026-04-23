# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : state.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Persistenter State pro Route+Tag.
#                  Entscheidet anhand der letzten Meldung, ob eine neue
#                  Notification gerechtfertigt ist (Anti-Spam-Logik).
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from checker import RouteCheckResult, TrainStatus


# ------------------------------------------------------------------------------
#  Konfiguration
# ------------------------------------------------------------------------------

STATE_DIR = Path(__file__).resolve().parent.parent / "state"

# Minimum Veränderung zwischen zwei Pings, damit nochmal gepingt wird.
# Verhindert Spam bei leicht wackelnder Verspätungs-Schätzung.
MIN_DELTA_FOR_REPING = 2  # Minuten

# Fenster für die "All-Clear"-Meldung relativ zur geplanten Abfahrt
ALL_CLEAR_WINDOW_START_MIN = 12  # frühestens 12 Min vor Abfahrt
ALL_CLEAR_WINDOW_END_MIN = 8     # spätestens 8 Min vor Abfahrt

# ------------------------------------------------------------------------------
#  Datenklasse für persistenten State
# ------------------------------------------------------------------------------

@dataclass
class RouteState:
    """Was wir uns pro Route+Tag merken."""

    last_check_at: Optional[str] = None        # ISO-String
    last_reported_delay: Optional[int] = None  # Minuten; None = noch nie gemeldet
    last_reported_status: Optional[str] = None # "on_time" | "delayed" | "cancelled"
    notification_count: int = 0                # Wie oft schon gepingt heute
    first_alert_at: Optional[str] = None       # ISO-String der ersten Alert-Meldung
    all_clear_sent: bool = False               # Immer eine Info senden auch wenn pünktlich

    @classmethod
    def load(cls, path: Path) -> "RouteState":
        """State aus JSON laden. Fehlende Datei → leerer State."""
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (json.JSONDecodeError, TypeError) as e:
            # Defensiv: bei kaputtem State lieber neu anfangen als crashen
            print(f"⚠️  State-Datei {path} defekt ({e}) — starte mit leerem State.")
            return cls()

    def save(self, path: Path) -> None:
        """State in JSON schreiben (atomar via temp-File + rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)  # atomarer Rename, kein halb-geschriebenes File möglich


# ------------------------------------------------------------------------------
#  Dateipfad-Konstruktion
# ------------------------------------------------------------------------------

def state_path_for(route_id: str, day: Optional[datetime] = None) -> Path:
    """Pfad zur State-Datei einer Route für einen bestimmten Tag."""
    day = day or datetime.now()
    date_str = day.strftime("%Y%m%d")
    return STATE_DIR / f"{route_id}_{date_str}.json"


# ------------------------------------------------------------------------------
#  Die eigentliche Entscheidungs-Logik
# ------------------------------------------------------------------------------

@dataclass
class NotificationDecision:
    """Ergebnis der 'Soll ich pingen?'-Entscheidung."""

    should_notify: bool
    reason: str                 # Menschenlesbare Erklärung (für Logs)
    new_state: "RouteState"     # State, der nach dem Ping gespeichert werden soll


def decide_notification(
    result: RouteCheckResult,
    previous_state: RouteState,
    *,
    alert_threshold_min: int,
    all_clear_window_start_min: int = ALL_CLEAR_WINDOW_START_MIN,
    all_clear_window_end_min: int = ALL_CLEAR_WINDOW_END_MIN,
) -> NotificationDecision:
    """Entscheidet, ob eine Notification verschickt werden soll.

    Args:
        result: Aktuelles Check-Ergebnis vom Checker.
        previous_state: State des letzten Checks (leer bei Erstlauf des Tages).
        alert_threshold_min: Minimale Verspätung für Erstmeldung (aus Route-Config).

    Returns:
        NotificationDecision mit should_notify, reason und neuem State.
    """
    # --- Neuen State aufbauen (kopieren + anpassen) ---
    new_state = RouteState(**asdict(previous_state))
    new_state.last_check_at = datetime.now().isoformat(timespec="seconds")

    status = result.status
    delay = result.delay_minutes
    prev_delay = previous_state.last_reported_delay
    prev_status = previous_state.last_reported_status

    # --- Case 1: Ausfall (höchste Priorität) ---
    if status == TrainStatus.CANCELLED:
        # Nur pingen, wenn vorher nicht schon als cancelled gemeldet
        if prev_status == TrainStatus.CANCELLED.value:
            return NotificationDecision(
                should_notify=False,
                reason="Bereits als ausgefallen gemeldet.",
                new_state=new_state,
            )

        new_state.last_reported_status = status.value
        new_state.notification_count += 1
        if new_state.first_alert_at is None:
            new_state.first_alert_at = new_state.last_check_at

        return NotificationDecision(
            should_notify=True,
            reason="Zug ist ausgefallen.",
            new_state=new_state,
        )

    # --- Case 2: Zug nicht im Plan gefunden ---
    if status == TrainStatus.NOT_FOUND:
        # Nur einmal pro Tag melden (sonst Spam)
        if previous_state.notification_count > 0 and prev_status == TrainStatus.NOT_FOUND.value:
            return NotificationDecision(
                should_notify=False,
                reason="Zug weiterhin nicht im Plan (bereits gemeldet).",
                new_state=new_state,
            )

        new_state.last_reported_status = status.value
        new_state.notification_count += 1
        if new_state.first_alert_at is None:
            new_state.first_alert_at = new_state.last_check_at

        return NotificationDecision(
            should_notify=True,
            reason="Zug im Plan nicht gefunden (Linienänderung? Feiertag?).",
            new_state=new_state,
        )

    # --- Case 3: On-Time Rückkehr nach vorheriger Verspätung (Entwarnung) ---
    if status == TrainStatus.ON_TIME and prev_status == TrainStatus.DELAYED.value:
        new_state.last_reported_status = status.value
        new_state.last_reported_delay = 0
        new_state.all_clear_sent = True   
        new_state.notification_count += 1

        return NotificationDecision(
            should_notify=True,
            reason="Zug ist wieder pünktlich (nach vorheriger Verspätungsmeldung).",
            new_state=new_state,
        )
    # --- Case 3b: All-Clear-Meldung ~10 Min vor Abfahrt ---
    # Einmal pro Tag, wenn Zug pünktlich und wir im Zeitfenster sind.
    if (
        status == TrainStatus.ON_TIME
        and not previous_state.all_clear_sent
        and result.planned_departure is not None
    ):
        from datetime import datetime as _dt
        now = _dt.now(result.planned_departure.tzinfo)
        minutes_to_departure = (result.planned_departure - now).total_seconds() / 60

        if all_clear_window_end_min <= minutes_to_departure <= all_clear_window_start_min:
            new_state.last_reported_status = status.value
            new_state.last_reported_delay = 0
            new_state.all_clear_sent = True
            new_state.notification_count += 1

            return NotificationDecision(
                should_notify=True,
                reason=f"All-Clear: Zug pünktlich, ~{int(minutes_to_departure)} Min vor Abfahrt.",
                new_state=new_state,
            )
        
    # --- Case 4: Pünktlich und war auch vorher pünktlich (oder noch nichts gemeldet) ---
    if status == TrainStatus.ON_TIME:
        # State aktualisieren, aber kein Ping
        new_state.last_reported_status = status.value
        new_state.last_reported_delay = 0
        return NotificationDecision(
            should_notify=False,
            reason="Zug fährt pünktlich.",
            new_state=new_state,
        )

    # --- Case 5: Verspätet ---
    if status == TrainStatus.DELAYED:
        # Erstmeldung: Schwelle prüfen
        if prev_delay is None or prev_status != TrainStatus.DELAYED.value:
            if delay < alert_threshold_min:
                # Unter der Schwelle — State updaten, nicht pingen
                new_state.last_reported_status = status.value
                new_state.last_reported_delay = delay
                return NotificationDecision(
                    should_notify=False,
                    reason=f"Verspätung {delay} Min < Schwelle {alert_threshold_min} Min.",
                    new_state=new_state,
                )

            # Erste echte Verspätungsmeldung
            new_state.last_reported_status = status.value
            new_state.last_reported_delay = delay
            new_state.all_clear_sent = True
            new_state.notification_count += 1
            if new_state.first_alert_at is None:
                new_state.first_alert_at = new_state.last_check_at

            return NotificationDecision(
                should_notify=True,
                reason=f"Erste Verspätungsmeldung: {delay} Min.",
                new_state=new_state,
            )

        # Folgemeldung: nur bei signifikanter Änderung
        delta = abs(delay - prev_delay)
        if delta < MIN_DELTA_FOR_REPING:
            return NotificationDecision(
                should_notify=False,
                reason=f"Änderung {delta} Min < {MIN_DELTA_FOR_REPING} Min — kein Update.",
                new_state=new_state,
            )

        # Neue Meldung mit geänderter Verspätung
        new_state.last_reported_status = status.value
        new_state.last_reported_delay = delay
        new_state.notification_count += 1

        trend = "↑" if delay > prev_delay else "↓"
        return NotificationDecision(
            should_notify=True,
            reason=f"Update: {prev_delay} → {delay} Min {trend}.",
            new_state=new_state,
        )

    # --- Fallback (sollte nie erreicht werden) ---
    return NotificationDecision(
        should_notify=False,
        reason=f"Unerwarteter Status: {status}",
        new_state=new_state,
    )