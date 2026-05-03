# ===========================================================================================
#  # BartoAI
# ===========================================================================================
#  Bereich . . . : Tooling/DBTicker
#  Datei . . . . : notifier.py
#  Autor . . . . : Bartosz Stryjewski
#  Erstellt am . : 21.04.2026
#  Erweitert am .: 01.05.2026 (barto-link Backend als Alternative zu Telegram)
#  Erweitert am .: 03.05.2026 (Strukturierte Metadaten via meta-Dict für DetailView)
# ------------------------------------------------------------------------------------------
#  Beschreibung  : Notify-Layer mit zwei austauschbaren Backends:
#                    - "telegram"   → Telegram-Bot, HTML-Format
#                    - "barto_link" → eigene iOS-App via push.barto.cloud
#                  Auswahl per .env (NOTIFY_BACKEND).
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
    """
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
                    "num_predict": 60,
                },
            },
            timeout=timeout,
        )
        r.raise_for_status()
        text = r.json().get("response", "").strip()
        first_line = text.split("\n")[0].strip()
        first_line = first_line.strip('"').strip("'").lstrip("-").strip()
        logger.info("Agent-Satz: %s", first_line)
        return first_line or None
    except (requests.RequestException, ValueError) as e:
        logger.warning("Ollama-Call für Agent-Satz fehlgeschlagen: %s", e)
        return None


# ------------------------------------------------------------------------------
#  Stufe 2: HTML-Nachricht bauen (Telegram)
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
    """Baut die finale HTML-Nachricht für Telegram."""
    emoji, status_label = STATUS_PRESENTATION.get(
        result.status,
        ("❓", "unbekannt"),
    )
    line = result.train_line or "?"
    delay = result.delay_minutes

    headline_parts = [f"{emoji} <b>{line} {status_label}</b>"]
    if result.status == TrainStatus.DELAYED and delay > 0:
        headline_parts[0] = f"{emoji} <b>{line} {status_label}: +{delay} Min</b>"

    lines = [headline_parts[0], ""]

    if result.destination:
        lines.append(f"<b>Richtung:</b> {result.destination}")

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

    if to_station_name and result.status != TrainStatus.CANCELLED:
        lines.append(f"<b>Aussteigen:</b> {to_station_name}")

    if result.delay_reason is not None and result.delay_reason.resolved.is_known:
        reason_text = result.delay_reason.resolved.text
        lines.append(f"<b>Grund:</b> {_escape_html(reason_text)}")

    if agent_sentence:
        lines.append("")
        lines.append(f"<i>{_escape_html(agent_sentence)}</i>")

    return "\n".join(lines)


def _escape_html(text: str) -> str:
    """Escape HTML-Sonderzeichen, damit Agent-Satz Telegram nicht bricht."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ------------------------------------------------------------------------------
#  Stufe 2b: Plain-Text-Nachricht für barto-link bauen
# ------------------------------------------------------------------------------

def build_push_payload(
    result: RouteCheckResult,
    agent_sentence: Optional[str],
    from_station_name: str,
    to_station_name: str,
) -> tuple[str, str]:
    """Baut Title + Body für die iOS-App via barto-link.

    Im Gegensatz zu Telegram (HTML) brauchen wir hier:
      - Title:  Eine prägnante Zeile mit Emoji + Status (max ~60 Zeichen)
      - Body:   Mehrzeiliger Plain-Text mit den Details

    Returns:
        (title, body) Tuple.
    """
    emoji, status_label = STATUS_PRESENTATION.get(
        result.status,
        ("❓", "unbekannt"),
    )
    line = result.train_line or "?"
    delay = result.delay_minutes

    # --- Title ---
    if result.status == TrainStatus.DELAYED and delay > 0:
        title = f"{emoji} {line} verspätet: +{delay} Min"
    else:
        title = f"{emoji} {line} {status_label}"

    # --- Body ---
    body_lines: list[str] = []

    if result.destination:
        body_lines.append(f"Richtung: {result.destination}")

    if result.planned_departure:
        soll = result.planned_departure.strftime("%H:%M")
        platform = f", Gleis {result.planned_platform}" if result.planned_platform else ""

        if result.status == TrainStatus.DELAYED and result.actual_departure:
            ist = result.actual_departure.strftime("%H:%M")
            # Push hat keinen Strikethrough — wir nutzen "→" für Verschiebung
            body_lines.append(
                f"Abfahrt: {soll} → {ist} ({from_station_name}{platform})"
            )
        elif result.status == TrainStatus.CANCELLED:
            body_lines.append(
                f"Geplante Abfahrt: {soll} ({from_station_name}{platform})"
            )
        else:
            body_lines.append(f"Abfahrt: {soll} ({from_station_name}{platform})")

    if to_station_name and result.status != TrainStatus.CANCELLED:
        body_lines.append(f"Aussteigen: {to_station_name}")

    if result.delay_reason is not None and result.delay_reason.resolved.is_known:
        body_lines.append(f"Grund: {result.delay_reason.resolved.text}")

    if agent_sentence:
        body_lines.append("")
        body_lines.append(agent_sentence)

    body = "\n".join(body_lines)
    return title, body


# ------------------------------------------------------------------------------
#  Stufe 2c: Strukturierte Metadaten für die iOS-DetailView
# ------------------------------------------------------------------------------

def build_train_meta(
    result: RouteCheckResult,
    from_station_name: str,
    to_station_name: str,
) -> dict:
    """Baut das `meta`-Dict für die iOS-App.

    Der Inhalt landet im APNs-Payload und in StoredNotification —
    dort liest die DetailView die Felder aus.

    Returns:
        Dict mit JSON-tauglichen Werten (None-Werte werden ausgelassen).
    """
    meta: dict = {
        "status": result.status.value,
        "delay_minutes": result.delay_minutes,
    }

    # Felder nur aufnehmen, wenn vorhanden
    if result.train_line:
        meta["train_line"] = result.train_line
    if result.train_number:
        meta["train_number"] = result.train_number
    if result.destination:
        meta["destination"] = result.destination
    if result.planned_platform:
        meta["planned_platform"] = result.planned_platform

    # Datums-Felder als ISO 8601 mit Timezone
    if result.planned_departure:
        meta["planned_departure"] = result.planned_departure.isoformat()
    if result.actual_departure:
        meta["actual_departure"] = result.actual_departure.isoformat()

    # Verspätungsgrund (resolved aus messagecodes.toml)
    if result.delay_reason and result.delay_reason.resolved.is_known:
        meta["delay_reason"] = result.delay_reason.resolved.text
        meta["delay_reason_severity"] = result.delay_reason.resolved.severity

    # Stationen für Strecken-Sektion in der App
    if from_station_name:
        meta["from_station"] = from_station_name
    if to_station_name:
        meta["to_station"] = to_station_name

    return meta


# ------------------------------------------------------------------------------
#  Stufe 3a: Telegram direkt ansprechen
# ------------------------------------------------------------------------------

def send_to_telegram(html_text: str) -> bool:
    """Schickt vorgefertigten HTML-Text direkt an den Telegram-Bot."""
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
#  Stufe 3b: barto-link Backend ansprechen
# ------------------------------------------------------------------------------

def send_to_barto_link(
    title: str,
    body: str,
    *,
    source: str = "dbticker.transit",
    priority: int = 5,
    meta: Optional[dict] = None,
) -> bool:
    """Schickt einen Push an das eigene barto-link Backend.

    Args:
        title:     Notification-Titel (eine Zeile, sichtbar im Lockscreen-Banner)
        body:      Notification-Body (mehrzeilig, sichtbar bei Expand)
        source:    Tag für App-seitige Filterung. Default: 'dbticker.transit'
        priority:  APNs-Priority (1-10). Default 5 = normal.
        meta:      Optionale strukturierte Zusatzdaten für die App-DetailView.

    Returns:
        True bei HTTP 200, False bei jedem Fehler.
    """
    backend_url = os.environ.get("BARTO_LINK_URL")
    api_token = os.environ.get("BARTO_LINK_API_TOKEN")

    if not backend_url or not api_token:
        logger.error(
            "barto-link-Send nicht möglich: BARTO_LINK_URL oder "
            "BARTO_LINK_API_TOKEN fehlt im Environment."
        )
        return False

    url = f"{backend_url.rstrip('/')}/push"

    # HTTP-Payload schrittweise bauen, damit meta nur eingehängt wird, falls vorhanden
    http_payload = {
        "title": title,
        "body": body,
        "source": source,
        "priority": priority,
    }
    if meta is not None:
        http_payload["meta"] = meta

    try:
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json=http_payload,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        sent = data.get("sent_to", 0)
        failed = data.get("failed", 0)

        if sent == 0:
            logger.warning(
                "barto-link akzeptiert, aber 0 Empfänger erreicht (failed=%d).",
                failed,
            )
            return False

        logger.info(
            "barto-link-Push erfolgreich (sent=%d, failed=%d).",
            sent, failed,
        )
        return True
    except requests.RequestException as e:
        logger.error("barto-link-Send fehlgeschlagen: %s", e)
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
    """Kompletter Notify-Flow: Agent-Satz → Format bauen → Backend senden.

    Backend wird via NOTIFY_BACKEND-Umgebungsvariable gewählt:
      - 'telegram'   (Default): HTML-Nachricht an Telegram-Bot
      - 'barto_link': Title + Body an eigene iOS-App via push.barto.cloud

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

    # --- 2. Backend wählen ---
    backend = os.environ.get("NOTIFY_BACKEND", "telegram").lower()

    if backend == "barto_link":
        # Plain-Text-Format für iOS-Push (Title + Body)
        title, body = build_push_payload(
            result,
            agent_sentence=agent_sentence,
            from_station_name=from_station_name,
            to_station_name=to_station_name,
        )

        # Strukturierte Metadaten für die DetailView
        meta = build_train_meta(
            result,
            from_station_name=from_station_name,
            to_station_name=to_station_name,
        )

        logger.debug(
            "Sende via barto-link: title=%r, meta_keys=%s",
            title,
            list(meta.keys()),
        )
        return send_to_barto_link(
            title=title,
            body=body,
            source="dbticker.transit",
            meta=meta,
        )

    elif backend == "telegram":
        # HTML-Format für Telegram
        html = build_telegram_html(
            result,
            agent_sentence=agent_sentence,
            from_station_name=from_station_name,
            to_station_name=to_station_name,
        )
        logger.debug("Sende via Telegram (HTML)")
        return send_to_telegram(html)

    else:
        logger.error("Unbekanntes NOTIFY_BACKEND: %r — Push übersprungen.", backend)
        return False