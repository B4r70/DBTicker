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


logger = logging.getLogger(__name__)

OPENCLAW_HOOK_URL = "http://127.0.0.1:3000/hooks/agent"


def notify_via_openclaw(
    message: str,
    *,
    name: str = "dbticker",
    channel: str = "telegram",
) -> bool:
    """Schickt einen Hook an den lokalen OpenClaw-Agent.

    Args:
        message: Die Anweisung an den Agent (was er formulieren soll).
        name: Für Session-Summary im OpenClaw-Hauptkontext.
        channel: Zustell-Channel (default telegram).

    Returns:
        True wenn der Hook angenommen wurde, False sonst.
    """
    token = os.environ.get("OPENCLAW_HOOK_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error(
            "OpenClaw-Hook nicht möglich: OPENCLAW_HOOK_TOKEN oder "
            "TELEGRAM_CHAT_ID fehlt im Environment."
        )
        return False

    try:
        r = requests.post(
            OPENCLAW_HOOK_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "message": message,
                "name": name,
                "agentId": "main",
                "deliver": True,
                "channel": channel,
                "to": chat_id,
            },
            timeout=10,
        )
        r.raise_for_status()
        run_id = r.json().get("runId", "unknown")
        logger.info("OpenClaw-Hook akzeptiert (runId=%s)", run_id)
        return True

    except requests.RequestException as e:
        logger.error("OpenClaw-Hook fehlgeschlagen: %s", e)
        return False