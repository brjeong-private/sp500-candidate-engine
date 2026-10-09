#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/sp500-candidate-engine
ARCHIVE=/tmp/sp500-candidate-engine.tar.gz

sudo mkdir -p "$APP_DIR"
sudo tar -xzf "$ARCHIVE" -C "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  build-essential \
  ca-certificates \
  libpq-dev \
  python3 \
  python3-pip \
  python3-venv

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install .

chmod 600 .env

sudo tee /etc/systemd/system/sp500-backfill.service >/dev/null <<'EOF'
[Unit]
Description=S&P 500 maximum-data historical backfill
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=azurebackfill
WorkingDirectory=/opt/sp500-candidate-engine
EnvironmentFile=/opt/sp500-candidate-engine/.env
ExecStart=/opt/sp500-candidate-engine/.venv/bin/python -m sp500_candidate_engine --env-file /opt/sp500-candidate-engine/.env run-backfill --start 2026-07-09 --end 2026-10-08
StandardOutput=append:/opt/sp500-candidate-engine/logs/backfill-service.log
StandardError=append:/opt/sp500-candidate-engine/logs/backfill-service.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl disable sp500-backfill.service >/dev/null 2>&1 || true

if systemctl list-timers --all | grep -qi shutdown; then
  echo "Unexpected shutdown-related systemd timer detected" >&2
  systemctl list-timers --all | grep -i shutdown >&2
  exit 1
fi
