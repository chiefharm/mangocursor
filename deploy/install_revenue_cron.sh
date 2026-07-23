#!/usr/bin/env bash
# Install daily revenue report cron on VPS (05:00 Europe/Moscow).
set -euo pipefail
ROOT="${1:-/opt/mango-pipeline}"
PYTHON="${ROOT}/.venv/bin/python"
SCRIPT="${ROOT}/revenue_report.py"
LOG_DIR="${ROOT}/logs"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv python: $PYTHON" >&2
  exit 1
fi
if [[ ! -f "$SCRIPT" ]]; then
  echo "Missing script: $SCRIPT" >&2
  exit 1
fi

"$PYTHON" -m pip install -q -r "${ROOT}/requirements.txt"

# VPS clock is usually UTC. Prefer CRON_TZ; fallback 02:00 UTC = 05:00 MSK.
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v "revenue_report.py" | grep -v '^CRON_TZ=Europe/Moscow$' >"$TMP" || true
{
  echo "CRON_TZ=Europe/Moscow"
  echo "0 5 * * * cd ${ROOT} && ${PYTHON} ${SCRIPT} --env ${ROOT}/.env >> ${LOG_DIR}/revenue_report.log 2>&1"
} >>"$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "Installed cron: 05:00 Europe/Moscow (CRON_TZ)"
crontab -l | tail -5
echo "Test: ${PYTHON} ${SCRIPT} --env ${ROOT}/.env --dry-run"
