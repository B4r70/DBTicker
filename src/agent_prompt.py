# ==========================================================================================
#  # BartoAI
# ==========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : agent_prompt.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 22.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Aufbereiten der Ausgabe für den LLM Agent
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ==========================================================================================
#
from __future__ import annotations
from datetime import datetime, timedelta
from checker import RouteCheckResult

# ------------------------------------------------------------------------------
#  Aufbereitung der LLM Ausgabe in Telegram
# ------------------------------------------------------------------------------

def build_agent_prompt(
    result: RouteCheckResult,
    reason: str,
    route: dict,
) -> str:
    """Baut den Prompt, den wir an OpenClaw schicken.

    Der Agent formuliert daraus die finale Telegram-Nachricht.
    Wir geben ihm strukturierten Kontext mit Tagesablauf-Bezug —
    damit die Meldungen NUTZER-zentriert klingen, nicht zug-zentriert.
    """
    status = result.status.value
    delay = result.delay_minutes

    my_dep_str = route.get("my_departure_time", "")
    my_dep_label = route.get("my_departure_label", "losfahren")
    arrival_dest = route.get("arrival_destination", result.destination or "")
    delay_shifts = route.get("delay_shifts_my_time", True)

    today = datetime.now()
    my_dep_dt = None
    if my_dep_str:
        hh, mm = my_dep_str.split(":")
        my_dep_dt = today.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)

    new_my_dep_dt = my_dep_dt
    if my_dep_dt and delay_shifts and delay > 0:
        new_my_dep_dt = my_dep_dt + timedelta(minutes=delay)

    lines = [
        "Du bist der DB-Ticker für Bartosz. Verfasse eine kurze, klare Telegram-Nachricht.",
        "WICHTIG: Schreibe NUTZER-zentriert, nicht zug-zentriert.",
        "Sprich Bartosz direkt an, beziehe dich auf SEINEN Tagesablauf.",
        "Maximal 2-3 Zeilen. Direkt, freundlich, ADHS-friendly. KEIN Preamble.",
        "",
        "── Kontext ──",
        f"Route: {result.route_label}",
        f"Bartosz fährt normalerweise um {my_dep_str} Uhr {my_dep_label}.",
    ]

    if arrival_dest:
        lines.append(f"Ziel: {arrival_dest}")

    lines += [
        "",
        "── Status ──",
        f"Zug-Status: {status}",
        f"Soll-Abfahrt: {result.planned_departure.strftime('%H:%M') if result.planned_departure else '—'}",
        f"Ist-Abfahrt:  {result.actual_departure.strftime('%H:%M') if result.actual_departure else '—'}",
        f"Verspätung: {delay} Min",
    ]

    if my_dep_dt:
        lines.append(f"Bartos' geplanter Aufbruch: {my_dep_dt.strftime('%H:%M')}")
        if new_my_dep_dt and new_my_dep_dt != my_dep_dt:
            lines.append(f"Bartos' NEUER Aufbruch: {new_my_dep_dt.strftime('%H:%M')} (verschoben um {delay} Min)")

    lines += [
        "",
        f"Grund für diese Nachricht: {reason}",
        "",
        "── Anweisungen für die Nachricht ──",
        "- Bei All-Clear: 'Du kannst wie geplant um XX:XX [Aktion]. Zug pünktlich.'",
        "- Bei Verspätung MIT delay_shifts: 'Du kannst X Min später [Aktion]. Neuer Aufbruch: XX:XX.'",
        "- Bei Verspätung OHNE delay_shifts: 'Zug X Min verspätet. Du fährst trotzdem um XX:XX zum Bahnhof.'",
        "- Bei Ausfall: 'Achtung: Zug fällt aus. Schau in DB Navigator nach Alternative.'",
        "- Bei Entwarnung: 'Aktualisierung: Zug doch wieder pünktlich. Geplanter Aufbruch um XX:XX gilt.'",
    ]

    return "\n".join(lines)