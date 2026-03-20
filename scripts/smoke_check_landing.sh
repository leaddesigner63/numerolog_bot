#!/usr/bin/env bash
set -euo pipefail

LANDING_URL="${LANDING_URL:-}"
LANDING_TELEGRAM_BOT_USERNAME="${LANDING_TELEGRAM_BOT_USERNAME:-numminnbot}"
LANDING_EXPECTED_CTA="${LANDING_EXPECTED_CTA:-}"
LANDING_ASSET_URLS="${LANDING_ASSET_URLS:-}"

if [ -n "$LANDING_TELEGRAM_BOT_USERNAME" ] && [ -z "$LANDING_EXPECTED_CTA" ]; then
  LANDING_TELEGRAM_BOT_USERNAME="${LANDING_TELEGRAM_BOT_USERNAME#@}"
  LANDING_EXPECTED_CTA="https://t.me/$LANDING_TELEGRAM_BOT_USERNAME"
fi

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

  mapfile -t telegram_links < <(grep -Eo 'https://t\.me/[^"'"'"'[:space:]<]+' "$TMP_HTML" | sort -u)
  if [ "${#telegram_links[@]}" -eq 0 ]; then
    echo "Smoke-check: в HTML не найдено Telegram-ссылок"
    exit 1
  fi

  for telegram_link in "${telegram_links[@]}"; do
    if [[ "$telegram_link" != "$LANDING_EXPECTED_CTA"* ]]; then
      echo "Smoke-check: найден неожиданный Telegram CTA: $telegram_link (ожидается префикс $LANDING_EXPECTED_CTA)"
      exit 1
    fi
  done

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
