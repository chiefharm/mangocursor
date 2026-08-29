#!/usr/bin/env bash
# Install try-on token usage cron on NSK (prod data). 02:05 UTC = 05:05 MSK.
# Sends Telegram via TRYON_TG_RELAY_URL (Amsterdam).
set -euo pipefail
ROOT="${1:-/opt/mango-pipeline}"
# Prefer tryon venv (has deps); fall back to mango-pipeline
if [[ -x /opt/soco-tryon/.venv/bin/python ]]; then
  PYTHON="/opt/soco-tryon/.venv/bin/python"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi
SCRIPT="${ROOT}/tryon_usage_report.py"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

if [[ ! -f "$SCRIPT" ]]; then
  echo "Missing script: $SCRIPT" >&2
  exit 1
fi

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "tryon_usage_report.py" >"$TMP" || true
echo "5 2 * * * cd ${ROOT} && ${PYTHON} ${SCRIPT} --env ${ROOT}/.env --tryon-env /opt/soco-tryon/.env --data-dir /opt/soco-tryon/data >> ${LOG_DIR}/tryon_usage_report.log 2>&1" >>"$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "Installed cron on this host: 02:05 UTC (= 05:05 Europe/Moscow)"
crontab -l | grep tryon_usage || true
echo "Test: ${PYTHON} ${SCRIPT} --env ${ROOT}/.env --tryon-env /opt/soco-tryon/.env --dry-run"
