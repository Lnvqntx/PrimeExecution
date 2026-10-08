#!/usr/bin/env bash
# Installs and starts the bot as a systemd service on the EC2 instance.
# Run from anywhere:  bash deploy/install_service.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$DIR/.venv/bin/python"

[ -x "$PY" ] || { echo "ERROR: no virtualenv at $DIR/.venv (create it first, see README)"; exit 1; }
[ -f "$DIR/.env" ] || { echo "ERROR: $DIR/.env is missing (copy .env.example and fill it in)"; exit 1; }
grep -q '^LIVE_TRADING=true' "$DIR/.env" || echo "WARNING: LIVE_TRADING is not 'true' in .env: the bot will run DRY (no orders)"

sudo tee /etc/systemd/system/primebot.service >/dev/null <<EOF
[Unit]
Description=Prime Execution trading bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(whoami)
WorkingDirectory=$DIR
ExecStart=$PY -m prime --live
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now primebot
sleep 5
sudo systemctl --no-pager --lines=0 status primebot || true
echo
echo "Bot logs:   tail -f $DIR/logs/bot.log"
echo "Status:     $PY -m prime.report"
