#!/usr/bin/env bash
set -euo pipefail

LANDING_URL="${LANDING_URL:-}"
LANDING_EXPECTED_CTA="${LANDING_EXPECTED_CTA:-}"
LANDING_ASSET_URLS="${LANDING_ASSET_URLS:-}"

if [ -z "$LANDING_URL" ]; then
  echo "LANDING_URL не задан, smoke-check пропущен (без ошибки)."
  exit 0
fi

TMP_HTML="$(mktemp)"
trap 'rm -f "$TMP_HTML"' EXIT

status_code="$(curl -sS -L -o "$TMP_HTML" -w '%{http_code}' "$LANDING_URL")"
if [ "$status_code" -lt 200 ] || [ "$status_code" -ge 400 ]; then
  echo "Smoke-check: лендинг недоступен ($LANDING_URL), HTTP $status_code"
  exit 1
fi

echo "Smoke-check: лендинг доступен ($LANDING_URL), HTTP $status_code"

if [ -n "$LANDING_EXPECTED_CTA" ]; then
  if ! grep -Fq "$LANDING_EXPECTED_CTA" "$TMP_HTML"; then
    echo "Smoke-check: CTA-ссылка не найдена: $LANDING_EXPECTED_CTA"
    exit 1
  fi
  echo "Smoke-check: CTA-ссылка найдена"
else
  echo "LANDING_EXPECTED_CTA не задан, проверка CTA пропущена."
fi

if [ -n "$LANDING_ASSET_URLS" ]; then
  IFS=',' read -r -a assets <<< "$LANDING_ASSET_URLS"
  for asset in "${assets[@]}"; do
    asset_trimmed="$(echo "$asset" | xargs)"
    [ -z "$asset_trimmed" ] && continue
    asset_status="$(curl -sS -L -o /dev/null -w '%{http_code}' "$asset_trimmed")"
    if [ "$asset_status" -lt 200 ] || [ "$asset_status" -ge 400 ]; then
      echo "Smoke-check: asset недоступен ($asset_trimmed), HTTP $asset_status"
      exit 1
    fi
    echo "Smoke-check: asset доступен ($asset_trimmed), HTTP $asset_status"
  done
else
  echo "LANDING_ASSET_URLS не задан, проверка ассетов пропущена."
fi
