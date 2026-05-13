# ==========================================================================
#  DBTicker · src/calendar_check.py
#  ----------------------------------------------------
#  ICS-Kalender-Check für die Ermittlung der Office-Tage
#
#  Autor:  Bartosz Stryjewski
#  Datum:  13.05.2026
# ==========================================================================
#
"""Abfrage des prosozial-Arbeitskalenders via ICS-Subscription.

Liefert den heutigen Office-Status ("office" | "remote" | "unknown")
basierend auf Kalendereinträgen. main.py prüft pro Lauf einmal:
- "remote"          → alle Routen überspringen
- "office"/"unknown" → normal weiter (Wochentag-/Fenster-Filter greifen)

Cache: File-Cache für CACHE_TTL_MIN Minuten. Bei Netzwerkfehlern wird ein
Stale-Cache bis STALE_FALLBACK_MAX_HOURS akzeptiert.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Optional

import requests
from icalendar import Calendar

from src.state import BERLIN, STATE_DIR

# Konfiguration und Konstanten
# ----------------------------------------------------

logger = logging.getLogger(__name__)

CACHE_FILE = STATE_DIR / "calendar_cache.ics"
 
# Wie lange darf der File-Cache benutzt werden, bevor neu geholt wird?
CACHE_TTL_MIN = 60
 
# Bei Netzwerkfehler: bis zu wie viele Stunden alte Daten akzeptieren wir noch?
STALE_FALLBACK_MAX_HOURS = 24
 
# Timeout für den HTTP-Fetch — bewusst kurz, weil DBTicker minütlich läuft
# und nicht durch eine langsame ICS-Antwort blockiert werden darf.
FETCH_TIMEOUT_SEC = 5
 
# Substring-Match auf SUMMARY, case-insensitive.
# Bei Mehrfach-Treffern an einem Tag gewinnt "office" (sicher = überwachen).
OFFICE_KEYWORDS = ["Büro Lahnstein"]
REMOTE_KEYWORDS = ["Mobiles Arbeiten"]
 
 
CalendarStatus = Literal["office", "remote", "unknown"]
 
 
# ------------------------------------------------------------------------------
#  Public Result-Type
# ------------------------------------------------------------------------------
 
@dataclass(frozen=True)
class CalendarCheck:
    """Ergebnis einer Kalender-Abfrage für einen bestimmten Tag.
 
    `status` ist die Quintessenz für main.py. `reason` und `matched_summary`
    sind für Logs/Debugging — damit man im Journal direkt sieht, *warum*
    DBTicker eine Route übersprungen oder freigeschaltet hat.
    """
    status: CalendarStatus
    reason: str
    matched_summary: Optional[str] = None
 
 
# ------------------------------------------------------------------------------
#  Public API
# ------------------------------------------------------------------------------
 
def get_status_for(target_date: date) -> CalendarCheck:
    """Hauptfunktion: liefert den Office-Status für ein bestimmtes Datum.

    `target_date` ist ein lokales Berlin-Datum (kein datetime!) — wir
    fragen "ist heute Büro oder HO" und brauchen dafür keine Uhrzeit.

    URL kommt aus ENV-Variable CALENDAR_ICS_URL. Fehlt sie, liefern wir
    "unknown" zurück → Fallback auf active_days aus routes.toml.
    """
    url = os.environ.get("CALENDAR_ICS_URL")
    if not url:
        return CalendarCheck(
            status="unknown",
            reason="CALENDAR_ICS_URL nicht gesetzt",
        )
 
    ics_text = _load_ics(url)
    if ics_text is None:
        return CalendarCheck(
            status="unknown",
            reason="ICS konnte weder frisch geholt noch aus Cache gelesen werden",
        )
 
    try:
        return _classify_day(ics_text, target_date)
    except Exception as e:
        # Defensiv: ein einzelnes kaputtes Event soll nicht den ganzen Lauf
        # zerschießen. Im Zweifel "unknown" zurück → Fallback auf active_days.
        logger.warning("Kalender-Parsing fehlgeschlagen: %s", e)
        return CalendarCheck(
            status="unknown",
            reason=f"Parse-Fehler: {e}",
        )
 
 
# ------------------------------------------------------------------------------
#  Loader mit Cache und Stale-Fallback
# ------------------------------------------------------------------------------
 
def _load_ics(url: str) -> Optional[str]:
    """Holt den ICS-Inhalt — bevorzugt aus Cache, sonst frisch über HTTP.
 
    Strategie:
      1. Cache vorhanden und jünger als CACHE_TTL_MIN → Cache nehmen
      2. Sonst HTTP-Fetch versuchen → bei Erfolg Cache schreiben + zurückgeben
      3. Wenn Fetch fehlschlägt, aber Cache vorhanden und nicht zu alt → Cache
      4. Sonst None (Caller liefert "unknown")
    """
    cache_age_min = _cache_age_minutes()
 
    if cache_age_min is not None and cache_age_min < CACHE_TTL_MIN:
        logger.debug("ICS-Cache frisch (%.1f Min alt) — kein Fetch", cache_age_min)
        return _read_cache()
 
    # Cache zu alt oder nicht vorhanden → Fetch versuchen
    fresh = _fetch_ics(url)
    if fresh is not None:
        _write_cache(fresh)
        return fresh
 
    # Fetch fehlgeschlagen — wenn Cache noch existiert und nicht uralt ist,
    # nehmen wir den Stale-Cache. Besser veraltete Wahrheit als gar keine.
    if cache_age_min is not None and cache_age_min < STALE_FALLBACK_MAX_HOURS * 60:
        logger.warning(
            "ICS-Fetch fehlgeschlagen — nutze Stale-Cache (%.1f Min alt)",
            cache_age_min,
        )
        return _read_cache()
 
    logger.error("ICS-Fetch fehlgeschlagen und kein nutzbarer Cache vorhanden")
    return None
 
 
def _cache_age_minutes() -> Optional[float]:
    """Alter der Cache-Datei in Minuten. None, wenn die Datei nicht existiert."""
    try:
        mtime = CACHE_FILE.stat().st_mtime
    except FileNotFoundError:
        return None
    return (datetime.now().timestamp() - mtime) / 60
 
 
def _read_cache() -> Optional[str]:
    """Liest die Cache-Datei. Bei Fehler: None (Caller fällt auf Fetch zurück)."""
    try:
        return CACHE_FILE.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Cache-Lesen fehlgeschlagen: %s", e)
        return None
 
 
def _write_cache(content: str) -> None:
    """Schreibt den Cache atomar (temp + rename), damit nie ein halb-fertiges
    File entstehen kann, falls der Prozess während des Schreibens stirbt."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(CACHE_FILE.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except OSError as e:
        # Cache-Schreiben ist nicht kritisch — wir können trotzdem weitermachen.
        # Beim nächsten Lauf wird halt nochmal frisch geholt.
        logger.warning("Cache-Schreiben fehlgeschlagen: %s", e)
 
 
def _fetch_ics(url: str) -> Optional[str]:
    """HTTP-GET auf die ICS-URL. Bei Fehler: None + Log.
 
    Wir dekodieren die Bytes BEWUSST selbst als UTF-8 statt response.text
    zu nutzen. Grund: prosozial sendet keinen charset= im Content-Type,
    und der HTTP-Standard schreibt dann ISO-8859-1 als Default vor.
    `requests` hält sich daran und liefert mojibake ("BÃ¼ro" statt "Büro").
    ICS-Dateien sind nach RFC 5545 immer UTF-8, also können wir das hier
    fest annehmen.
    """
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT_SEC)
        response.raise_for_status()
        return response.content.decode("utf-8")
    except requests.RequestException as e:
        logger.warning("ICS-Fetch fehlgeschlagen: %s", e)
        return None
    except UnicodeDecodeError as e:
        logger.warning("ICS ist kein gültiges UTF-8: %s", e)
        return None
 
 
# ------------------------------------------------------------------------------
#  Klassifikations-Logik
# ------------------------------------------------------------------------------
 
def _classify_day(ics_text: str, target_date: date) -> CalendarCheck:
    """Sucht in der ICS-Datei nach Events, die `target_date` (lokal Berlin)
    abdecken, und klassifiziert anhand der OFFICE/REMOTE-Keywords.
 
    Wichtig: prosozial liefert mehrtägige "Büro Lahnstein"-Blöcke
    (z.B. DTSTART 11.05. 22:00Z, DTEND 13.05. 22:00Z → in Berlin-Zeit
    12.05. 00:00 bis 14.05. 00:00, was bedeutet: gilt am 12.05. und 13.05.).
    Wir prüfen daher INKLUSIV: "target_date liegt zwischen Start-Datum
    und End-Datum (exklusiv) in lokaler Berlin-Zeit".
    """
    cal = Calendar.from_ical(ics_text)
 
    found_office: Optional[str] = None
    found_remote: Optional[str] = None
 
    for component in cal.walk("VEVENT"):
        summary_raw = component.get("SUMMARY")
        if summary_raw is None:
            continue
        summary = str(summary_raw)
 
        if not _event_covers_date(component, target_date):
            continue
 
        if _matches_any(summary, OFFICE_KEYWORDS):
            found_office = summary
            # office gewinnt sofort — kein weiteres Suchen nötig
            break
        if _matches_any(summary, REMOTE_KEYWORDS):
            found_remote = summary
            # nicht breaken: vielleicht kommt noch ein Office-Event
 
    if found_office is not None:
        return CalendarCheck(
            status="office",
            reason="Kalender: Büro-Eintrag gefunden",
            matched_summary=found_office,
        )
    if found_remote is not None:
        return CalendarCheck(
            status="remote",
            reason="Kalender: Mobiles-Arbeiten-Eintrag gefunden",
            matched_summary=found_remote,
        )
    return CalendarCheck(
        status="unknown",
        reason="Kein passender Eintrag für diesen Tag",
    )
 
 
def _matches_any(text: str, keywords: list[str]) -> bool:
    """Case-insensitive Substring-Match gegen eine Liste von Keywords."""
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)
 
 
def _event_covers_date(component, target_date: date) -> bool:
    """Prüft, ob `target_date` (Berlin) innerhalb des Event-Zeitraums liegt.
 
    ICS-Konventionen, mit denen wir umgehen müssen:
      a) Ganztages-Events mit DATE-Werten (DTSTART;VALUE=DATE:20260513)
         → werden von icalendar als `datetime.date` zurückgegeben
      b) Zeitbasierte Events in UTC (DTSTART:20260511T220000Z)
         → werden als tz-aware `datetime` zurückgegeben, müssen für den
         Datums-Vergleich nach Berlin umgerechnet werden
      c) Floating Times ohne TZID → nehmen wir als Berlin an
 
    DTEND ist exklusiv (ICS-Standard): ein Event mit DTSTART=12.05. und
    DTEND=14.05. läuft am 12.05. und 13.05., aber NICHT am 14.05.
    """
    dtstart_raw = component.get("DTSTART")
    dtend_raw = component.get("DTEND")
    if dtstart_raw is None or dtend_raw is None:
        return False
 
    start_date = _to_berlin_date(dtstart_raw.dt)
    end_date = _to_berlin_date(dtend_raw.dt)
 
    # DTEND ist exklusiv → echtes < statt <=
    return start_date <= target_date < end_date
 
 
def _to_berlin_date(value) -> date:
    """Konvertiert eine ICS-Zeitangabe in ein lokales Berlin-Datum.
 
    Bei datetime: nach Berlin umrechnen, dann nur das Datum nehmen.
    Bei date: direkt zurück (ganztägiger Eintrag, schon in lokaler Logik).
    """
    if isinstance(value, datetime):
        # tz-naive datetimes als Berlin behandeln (Floating Time)
        if value.tzinfo is None:
            value = value.replace(tzinfo=BERLIN)
        return value.astimezone(BERLIN).date()
    if isinstance(value, date):
        return value
    raise TypeError(f"Unerwarteter Zeit-Typ in ICS: {type(value)}")
 