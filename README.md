# 🚆 DBTicker

Persönlicher Verspätungs-Ticker für feste Pendelverbindungen der Deutschen Bahn.

Schickt Telegram-Nachrichten über den lokalen OpenClaw-Agent, wenn der Zug
verspätet ist, ausfällt — oder pünktlich kommt und du beruhigt losgehen kannst.

## Warum

Wer morgens pendelt, will nicht im DB Navigator stochern, um zu wissen ob der
Zug kommt. DBTicker prüft die konfigurierten Stamm-Verbindungen automatisch im
Hintergrund und meldet sich **nur dann**, wenn's relevant ist:

- ~10 Min vor Abfahrt: kurzer "alles pünktlich"-Ping
- Bei Verspätung ≥ 3 Min: sofortige Info
- Bei signifikanter Änderung (z.B. Verspätung wächst von 5 auf 10 Min): Update
- Bei Ausfall: Alarm
- Bei Entwarnung nach vorheriger Verspätung: "wieder pünktlich"

Kein Spam. Jede Meldung hat einen Grund.

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│  systemd-Timer (alle 5 Min, Mo-Fr)                          │
│    └─> dbticker.service                                     │
│         └─> src/main.py                                     │
│              ├─ Config laden (routes.toml + mystations.toml)│
│              ├─ Filter: ist Route im Check-Fenster?         │
│              └─ pro aktive Route:                           │
│                   ├─ DB Timetables API abfragen             │
│                   ├─ State prüfen (schon gepingt heute?)    │
│                   └─ ggf. POST /hooks/agent an OpenClaw     │
│                        └─> Telegram                         │
└─────────────────────────────────────────────────────────────┘
```

**Trennung der Verantwortlichkeiten:**

- `db_client.py` — Zugriff auf die DB Timetables API (Plan + Changes als XML)
- `checker.py` — Zug-Identifikation, Verspätungs-Berechnung
- `state.py` — Zustandsmaschine pro Route/Tag, Anti-Spam-Logik
- `notifier.py` — OpenClaw-Hook-Call
- `agent_prompt.py` — Formulierungs-Anweisungen für den Agent
- `main.py` — Orchestrator

## Technologie

- Python 3.12 + `deutsche-bahn-api` (PyPI)
- TOML für Konfiguration (`tomllib` aus stdlib)
- JSON für persistenten State
- systemd-Timer für Scheduling
- OpenClaw `/hooks/agent` für User-facing Notifications
- Zeitzone: `Europe/Berlin` (explizit gesetzt, nicht Server-abhängig)

## Voraussetzungen

- Linux-Server mit Python 3.12 und systemd
- [OpenClaw](https://openclaw.ai) inklusive konfiguriertem Telegram-Channel
  und aktiviertem `/hooks/agent`-Endpoint
- Account bei [DB API Marketplace](https://developers.deutschebahn.com/)
  mit Subscription auf die Timetables-API (Free-Plan reicht)

## Setup

### 1. Repo klonen & venv

```bash
git clone https://git.barto.cloud/barto/DBTicker.git
cd DBTicker
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. DB-API-Zugang einrichten

1. App auf [developers.deutschebahn.com](https://developers.deutschebahn.com/) anlegen
2. Timetables-API abonnieren (Free-Plan)
3. Client ID + Secret notieren

### 3. `.env` anlegen

```bash
cp .env.example .env   # falls Template existiert, sonst neu anlegen
nvim .env
```

Inhalt:

```dotenv
# DB Marketplace API
DB_API_CLIENT_ID=<deine_client_id>
DB_API_CLIENT_SECRET=<dein_client_secret>

# Telegram + OpenClaw
TELEGRAM_CHAT_ID=<deine_telegram_user_id>
OPENCLAW_HOOK_TOKEN=<hook_token_aus_openclaw_env>
```

### 4. Stationen konfigurieren

EVA-Nummern für deine Stationen finden:

```bash
python tools/find_station.py "Bad Ems West" --add bademswest
python tools/find_station.py Niederlahnstein --add niederlahnstein
```

Die Treffer werden automatisch in `config/mystations.toml` geschrieben.

### 5. Routen definieren

`config/routes.toml` anpassen — siehe die mitgelieferte Beispielkonfiguration.
Pro Route setzt du Abfahrtszeit, Linie, Richtung, Alert-Schwelle und
aktive Wochentage.

### 6. Manueller Testlauf

```bash
python src/main.py
```

Wenn gerade keine Route im Check-Fenster ist, sollte die Ausgabe
`Fertig. 0 Routen aktiv geprüft.` lauten — das ist normal.

### 7. systemd-Integration

```bash
sudo cp integrations/openclaw/dbticker.sh /var/lib/openclaw/skills/dbticker/
sudo chmod +x /var/lib/openclaw/skills/dbticker/dbticker.sh

sudo cp integrations/openclaw/dbticker.service /etc/systemd/system/
sudo cp integrations/openclaw/dbticker.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now dbticker.timer
```

Verifizieren:

```bash
systemctl list-timers 'dbticker*'
journalctl -u dbticker.service --since "10 minutes ago"
```

## Projektstruktur

```
dbticker/
├── config/
│   ├── mystations.toml       # Bekannte Stationen (EVA-Nummern etc.)
│   └── routes.toml           # Überwachte Verbindungen
├── src/
│   ├── main.py               # Entry Point für systemd
│   ├── db_client.py          # HTTP + XML-Parsing der DB-API
│   ├── checker.py            # Zug-Identifikation + Status-Berechnung
│   ├── state.py              # Persistenter State + Notify-Entscheidung
│   ├── notifier.py           # OpenClaw-Hook-Call
│   └── agent_prompt.py       # Prompt-Text für OpenClaw-Agent
├── tools/
│   ├── find_station.py       # EVA-Nummern per Name suchen
│   └── test_*.py             # Smoketests für die Module
├── integrations/openclaw/
│   ├── dbticker.sh           # OpenClaw-Skill-Wrapper
│   ├── dbticker.service      # systemd-Unit
│   └── dbticker.timer        # systemd-Timer (alle 5 Min)
├── state/                    # Runtime: JSON pro Route+Tag (nicht versioniert)
├── requirements.txt
└── README.md
```

## Benachrichtigungslogik

Pro Route und Tag wird ein State-File unter `state/<route_id>_<YYYYMMDD>.json`
geführt. Die Entscheidungsregeln:

| Zustand | Vorher-Meldung | Neue Meldung? |
|---|---|---|
| Pünktlich, ~10 Min vor Abfahrt | keine | ✅ "All-Clear"-Ping (1× täglich) |
| Verspätung ≥ Schwelle | keine | ✅ Erstmeldung |
| Verspätung wächst/schrumpft ≥ 2 Min | Verspätung gemeldet | ✅ Update |
| Verspätung ändert sich < 2 Min | Verspätung gemeldet | ❌ kein Spam |
| Pünktlich wiederhergestellt | Verspätung gemeldet | ✅ Entwarnung |
| Ausfall | noch nicht gemeldet | ✅ Alarm |
| Zug nicht im Plan | noch nicht gemeldet | ✅ einmalig Warnung |

## Konfigurations-Referenz: routes.toml

```toml
[[routes]]
id                      = "hin-0631"                  # eindeutige ID (State-Files)
label                   = "🚆 Morgens Bad Ems → Koblenz"
from_station            = "bademswest"                # Key aus mystations.toml
to_station              = "niederlahnstein"
scheduled_departure     = "06:31"                     # HH:MM, Europe/Berlin
line                    = "RB23"                      # exakte Linie
direction_contains      = "Koblenz"                   # Substring im Ziel
check_window_before_min = 60                          # wie früh prüfen?
check_window_after_min  = 5                           # wie lange noch prüfen?
alert_threshold_min     = 3                           # ab wann pingen?
active_days             = ["mo", "tu", "we", "th", "fr"]
```

## Logs & Debugging

Alles läuft via systemd-Journal:

```bash
# Live beobachten
journalctl -u dbticker.service -f

# Letzte 50 Läufe
journalctl -u dbticker.service -n 50 --no-pager

# Heutige Läufe
journalctl -u dbticker.service --since today
```

## Lizenz

Persönliches Projekt, alle Rechte vorbehalten.

## Credits

- [`deutsche-bahn-api`](https://pypi.org/project/deutsche-bahn-api/) — Python-Wrapper für die DB Timetables API
- [OpenClaw](https://openclaw.ai) — Personal AI Assistant für die Telegram-Anbindung
- Deutsche Bahn — für ausreichend Verspätungen, damit dieses Tool überhaupt Sinn ergibt 🙃