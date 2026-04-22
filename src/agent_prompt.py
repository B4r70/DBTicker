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

from checker import RouteCheckResult, TrainStatus

# ------------------------------------------------------------------------------------------
#  Agent Prompt aufbereiten
# ------------------------------------------------------------------------------------------

def build_agent_prompt(
    result: RouteCheckResult,
    reason: str,
    route: dict,
) -> str:
    """Prompt, der den Agent EINEN Satz mit Tagesablauf-Bezug liefern lässt.

    Der Agent bekommt nur die abstrakte Situation, keine Daten zum Formatieren.
    Alle technischen Infos (Uhrzeiten, Gleis, Zugnummer) baut Python im
    HTML-Template selbst ein — der Agent ergänzt nur eine persönliche Note.
    """
    status = result.status.value
    delay = result.delay_minutes

    # Tagesablauf-Felder aus der Route
    my_dep_str = route.get("my_departure_time", "")
    my_dep_label = route.get("my_departure_label", "losfahren")
    delay_shifts = route.get("delay_shifts_my_time", True)

    # Verschobene Aufbruchszeit berechnen (falls relevant)
    new_dep_str = None
    if my_dep_str and delay_shifts and delay > 0:
        hh, mm = my_dep_str.split(":")
        today = datetime.now()
        new_dep_dt = today.replace(hour=int(hh), minute=int(mm)) + timedelta(minutes=delay)
        new_dep_str = new_dep_dt.strftime("%H:%M")

    # Situation-Beschreibung für den Agent
    situation_lines = [f"Status: {status}"]
    if delay > 0:
        situation_lines.append(f"Verspätung: {delay} Min")
    # Grund, wenn bekannt (sonst leaves den Prompt unverstört)
    if result.delay_reason is not None and result.delay_reason.resolved.is_known:
        situation_lines.append(f"Verspätungsgrund: {result.delay_reason.resolved.text}")
    if my_dep_str:
        situation_lines.append(f"Geplanter Aufbruch: {my_dep_str} ({my_dep_label})")
        if new_dep_str and delay_shifts:
            situation_lines.append(f"Neuer Aufbruch wegen Verspätung: {new_dep_str}")
        elif delay > 0 and not delay_shifts:
            situation_lines.append("Aufbruch bleibt gleich (warte am Bahnhof)")

    situation_lines.append(f"Anlass: {reason}")

    situation_block = "\n".join(f"  {line}" for line in situation_lines)

    return f"""Du erstellst EINEN einzigen kurzen Satz auf Deutsch für Bartosz.

WICHTIG:
- Genau EIN Satz, maximal 15 Wörter.
- Kein Zug-Jargon, kein "RB23", keine Uhrzeiten (die hat Python schon im Template).
- Auf den Tagesablauf bezogen, nicht auf den Zug.
- ADHS-friendly: direkt, klar, freundlich.
- Kein Preamble, kein "Ich denke", nur der Satz selbst.
- Keine Emojis, kein Markdown, keine Formatierung.

Situation:
{situation_block}

Beispiele für guten Output:
- "Du kannst wie geplant starten, alles entspannt."
- "Nimm dir noch 8 Minuten extra — kein Stress."
- "Plan B nötig, schau kurz in den DB Navigator."
- "Alles wieder gut, Ursprungsplan bleibt."
- "Normale Abfahrt, der Tag beginnt wie vorgesehen."

Antworte NUR mit dem Satz. Nichts davor, nichts dahinter."""