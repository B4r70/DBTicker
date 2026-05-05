# DBTicker — OpenClaw Integration

Verkabelt dbticker als OpenClaw-Skill, sodass der systemd-Timer den
Pendlerlauf alle 5 Minuten anstößt und der Refresh-Endpoint von BartoLink
einzelne Routen on-demand neu prüfen kann.

## Setup

```bash
sudo cp dbticker.service /etc/systemd/system/
sudo cp dbticker.timer   /etc/systemd/system/
sudo cp dbticker.sh      /var/lib/openclaw/skills/dbticker/
sudo chmod +x            /var/lib/openclaw/skills/dbticker/dbticker.sh

sudo systemctl daemon-reload
sudo systemctl enable --now dbticker.timer
```

## Architektur

- **systemd-Timer** triggert alle 5 Min `dbticker.service`
- **Service** ruft `dbticker.sh run` auf, das wiederum den `dbticker`-Entry-Point
  aus der venv als User `barto` startet (`pip install -e .` macht den
  Entry-Point verfügbar)
- **dbticker** prüft pro Route, ob das Check-Fenster aktiv ist (Wochentag +
  Zeitfenster), und holt im Trefferfall den aktuellen Stand von der
  Deutsche-Bahn-API
- **Notify** via `POST /trips/events` → BartoLink → APNs → iOS-App
  (BartoLink übernimmt Trip-Aggregation und Push-Klassifikation)

## Manueller Refresh

Für den Refresh-Button in der iOS-App ruft BartoLink dbticker per Subprocess
mit `--route <id>`-Flag, der gezielt nur diese Route prüft (ohne
Wochentag-/Fenster-Filter):

```bash
dbticker.sh run --route hin-0628
```

Das Rate-Limiting (1 Refresh / 60s pro Trip + 30/h global) sitzt in
BartoLink, nicht hier.

## Historisch

Vor Sprint 2 (04.05.2026) lief Notify über einen OpenClaw-Hook
(`POST /hooks/agent`) zu einem Ollama-Agent, der eine Telegram-Nachricht
formuliert hat. Dieser Pfad ist komplett entfernt; die Hook-Konfiguration
und der Bot-Token sind nicht mehr nötig.