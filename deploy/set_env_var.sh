#!/bin/bash
# Append or replace env var in .env (no quotes in values)
set -euo pipefail
ENV_FILE="${1:-/opt/mango-pipeline/.env}"
KEY="$2"
VAL="$3"
touch "$ENV_FILE"
if grep -q "^${KEY}=" "$ENV_FILE" 2>/dev/null; then
  sed -i "s|^${KEY}=.*|${KEY}=\"${VAL}\"|" "$ENV_FILE"
else
  echo "${KEY}=\"${VAL}\"" >> "$ENV_FILE"
fi
