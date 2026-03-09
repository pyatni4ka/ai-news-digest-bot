#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ai-news-digest-bot}"
SERVICE_USER="${SERVICE_USER:-$USER}"
SERVICE_NAME="${SERVICE_NAME:-ai-news-digest}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "APP_DIR does not exist: $APP_DIR" >&2
  exit 1
fi

cd "$APP_DIR"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TMP_FILE="$(mktemp)"

sed \
  -e "s|__APP_DIR__|$APP_DIR|g" \
  -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
  deploy/systemd/ai-news-digest.service > "$TMP_FILE"

sudo mv "$TMP_FILE" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl status --no-pager "$SERVICE_NAME"
