# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : notifier.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
# ------------------------------------------------------------------------------------------
#  Beschreibung  : OpenClaw-Hook-Call zur Telegram-Zustellung.
#                  Agent bekommt die Route-Info + Delay-Kontext und formuliert
#                  daraus eine kompakte Nachricht für den User.
# ------------------------------------------------------------------------------------------
#  (C) Copyright 2026 Bartosz Stryjewski
#  All rights reserved
# ===========================================================================================
#
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from checker import RouteCheckResult, TrainStatus

# ------------------------------------------------------------------------------------------
#  Konfigurationen
# ------------------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

OPENCLAW_HOOK_URL = "http://127.0.0.1:3000/hooks/agent"
TELEGRAM_API_BASE = "https://api.telegram.org"

# ------------------------------------------------------------------------------
#  Stufe 1: Agent um einen Satz bitten
# ------------------------------------------------------------------------------

def request_agent_sentence(prompt: str, *, timeout: int = 30) -> Optional[str]:
    """Ruft OpenClaw-Agent und bittet um EINEN Satz (keine Telegram-Auslieferung).

    Der Hook wird mit deliver=false aufgerufen — der Agent antwortet synchron
    über die Session-History. Da der gesamte Request asynchron im Hintergrund
    läuft, müssen wir per Polling auf das Ergebnis warten.

    HINWEIS: OpenClaw's /hooks/agent ist primär fire-and-forget. Für einen
    synchronen Response nutzen wir hier den Fallback: wenn deliver=false ist,
    wird die Antwort nicht verschickt, aber auch nicht direkt zurückgegeben.
    In der Praxis nehmen wir stattdessen den direkten Ollama-Call — weil wir
    Vollkontrolle brauchen.
    """
    # FIXME: OpenClaw /hooks/agent gibt nur runId zurück, nicht die Antwort.
    # Wir brauchen einen Endpoint, der synchron antwortet, oder eine andere
    # Strategie. Siehe Hinweis weiter unten.

    # Für den Moment: direkter Ollama-Call, weil das am kontrollierbarsten ist.
    return _call_ollama_for_sentence(prompt, timeout=timeout)


def _call_ollama_for_sentence(prompt: str, *, timeout: int) -> Optional[str]:
    """Lokaler Ollama-Call, der einen einzelnen Satz zurückgibt."""
    try:
        r = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "dbticker:latest",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "num_predict": 60,   # max 60 Tokens
                },
            },
            timeout=timeout,
        )
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        # Defensive: Wenn mehrere Zeilen, nimm die erste
        first_line = text.split("\n")[0].strip()
        # Quotes und führende Bindestriche entfernen
        first_line = first_line.strip('"').strip("'").lstrip("-").strip()
        logger.info("Agent-Satz: %s", first_line)
        return first_line or None
    except (requests.RequestException, ValueError) as e:
        logger.warning("Ollama-Call für Agent-Satz fehlgeschlagen: %s", e)
        return None


# ------------------------------------------------------------------------------
#  Stufe 2: HTML-Nachricht bauen
# ------------------------------------------------------------------------------

# Status-Emojis und -Labels
STATUS_PRESENTATION = {
    TrainStatus.ON_TIME:   ("🟢", "pünktlich"),
    TrainStatus.DELAYED:   ("🔴", "verspätet"),
    TrainStatus.CANCELLED: ("⛔", "fällt aus"),
    TrainStatus.NOT_FOUND: ("⚠️", "nicht im Plan"),
}


def build_telegram_html(
    result: RouteCheckResult,
    agent_sentence: Optional[str],
    from_station_name: str,
    to_station_name: str,
) -> str:
    """Baut die finale HTML-Nachricht für Telegram.

    Struktur:
      [Emoji] [Linie] [Status-Label]
      [Optional: Verspätungs-Minuten]

      Zug: [Zugnummer] nach [Ziel]
      Abfahrt: [Zeit] (oder Soll→Ist) von [Station], Gleis [X]
      Ankunft: [Zeit] [Zielbahnhof]            ← nur wenn to_station-Info vorhanden

      [Agent-Satz]

      Weitere Halte: [Liste]
    """
    emoji, status_label = STATUS_PRESENTATION.get(
        result.status,
        ("❓", "unbekannt"),
    )
    line = result.train_line or "?"
    delay = result.delay_minutes

    # --- Headline ---
    headline_parts = [f"{emoji} <b>{line} {status_label}</b>"]
    if result.status == TrainStatus.DELAYED and delay > 0:
        headline_parts[0] = f"{emoji} <b>{line} {status_label}: +{delay} Min</b>"

    lines = [headline_parts[0], ""]

    # --- Zug-Info ---
    if result.destination:
        lines.append(f"<b>Richtung:</b> {result.destination}")

    # --- Abfahrt ---
    if result.planned_departure:
        soll = result.planned_departure.strftime("%H:%M")
        platform = f", Gleis {result.planned_platform}" if result.planned_platform else ""

        if result.status == TrainStatus.DELAYED and result.actual_departure:
            ist = result.actual_departure.strftime("%H:%M")
            lines.append(
                f"<b>Abfahrt:</b> <s>{soll}</s> → <b>{ist}</b> "
                f"({from_station_name}{platform})"
            )
        elif result.status == TrainStatus.CANCELLED:
            lines.append(
                f"<b>Geplante Abfahrt:</b> {soll} ({from_station_name}{platform})"
            )
        else:
            lines.append(f"<b>Abfahrt:</b> {soll} ({from_station_name}{platform})")

    # --- Zielbahnhof-Hinweis ---
    if to_station_name and result.status != TrainStatus.CANCELLED:
        lines.append(f"<b>Aussteigen:</b> {to_station_name}")

    # --- Verspätungsgrund (nur wenn bekannt, sonst weglassen) ---
    if result.delay_reason is not None and result.delay_reason.resolved.is_known:
        reason_text = result.delay_reason.resolved.text
        lines.append(f"<b>Grund:</b> {_escape_html(reason_text)}")

    # --- Agent-Satz ---
    if agent_sentence:
        lines.append("")
        lines.append(f"<i>{_escape_html(agent_sentence)}</i>")

    # --- Weitere Halte ---
    if result.status != TrainStatus.CANCELLED and hasattr(result, "_planned_path"):
        # Wir brauchen planned_path — das müssen wir noch ins RouteCheckResult reichen
        pass  # siehe Schritt 3 unten

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML-Sonderzeichen, damit Agent-Satz Telegram nicht bricht."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ------------------------------------------------------------------------------
#  Stufe 3: Telegram direkt ansprechen
# ------------------------------------------------------------------------------

def send_to_telegram(html_text: str) -> bool:
    """Schickt vorgefertigten HTML-Text direkt an den Telegram-Bot.

    Nutzt die Telegram-Bot-API via TELEGRAM_BOT_API und TELEGRAM_CHAT_ID
    aus dem Environment.
    """
    token = os.environ.get("TELEGRAM_BOT_API")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error(
            "Telegram-Send nicht möglich: TELEGRAM_BOT_API oder "
            "TELEGRAM_CHAT_ID fehlt im Environment."
        )
        return False

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": html_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        r.raise_for_status()
        if not r.json().get("ok"):
            logger.error("Telegram-API lehnte ab: %s", r.text)
            return False
        logger.info("Telegram-Nachricht erfolgreich gesendet.")
        return True
    except requests.RequestException as e:
        logger.error("Telegram-Send fehlgeschlagen: %s", e)
        return False


# ------------------------------------------------------------------------------
#  Public API: das ist was main.py nutzt
# ------------------------------------------------------------------------------

def notify(
    result: RouteCheckResult,
    *,
    agent_prompt: str,
    from_station_name: str,
    to_station_name: str = "",
) -> bool:
    """Kompletter Notify-Flow: Agent-Satz → HTML bauen → Telegram senden.

    Args:
        result: Das RouteCheckResult vom Checker.
        agent_prompt: Der Prompt für den Agent (von agent_prompt.build_agent_prompt).
        from_station_name: Lesbarer Name der Abfahrtsstation.
        to_station_name: Lesbarer Name der Ausstiegsstation.

    Returns:
        True bei Erfolg, False bei Fehler auf irgendeiner Stufe.
    """
    # --- 1. Agent-Satz holen (optional — bei Fehlschlag geht's ohne) ---
    agent_sentence = request_agent_sentence(agent_prompt)
    if not agent_sentence:
        logger.info("Kein Agent-Satz erhalten, sende ohne persönlichen Touch.")

    # --- 2. HTML-Nachricht bauen ---
    html = build_telegram_html(
        result,
        agent_sentence=agent_sentence,
        from_station_name=from_station_name,
        to_station_name=to_station_name,
    )

    # --- 3. An Telegram senden ---
    return send_to_telegram(html)