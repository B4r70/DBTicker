# OpenClaw Integration

## Deployment

```bash
# Skill-Wrapper
sudo cp integrations/openclaw/dbticker.sh /var/lib/openclaw/skills/dbticker/dbticker.sh
sudo chown clawdbot:openclaw /var/lib/openclaw/skills/dbticker/dbticker.sh
sudo chmod +x /var/lib/openclaw/skills/dbticker/dbticker.sh

# systemd
sudo cp integrations/openclaw/dbticker.service /etc/systemd/system/
sudo cp integrations/openclaw/dbticker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dbticker.timer
```

## Architektur

- systemd-Timer triggert alle 5 Min `dbticker.service`
- Service ruft `dbticker.sh run` auf, das ruft `src/main.py` als User `barto` auf
- Python checkt pro Route, ob jetzt Check-Fenster aktiv ist
- Notify via `POST /hooks/agent` → OpenClaw-Agent → Telegram

Same pattern as mailcontrol.
