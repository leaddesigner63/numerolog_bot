#!/usr/bin/env bash
set -euo pipefail

if [[ "${SMOKE_TEST_ENABLED:-0}" != "1" ]]; then
  echo "Smoke tests are disabled. Set SMOKE_TEST_ENABLED=1 to enable." >&2
  exit 0
fi

if [[ -n "${BOT_HEALTHCHECK_URL:-}" ]]; then
  echo "Checking healthcheck: $BOT_HEALTHCHECK_URL"
  curl -fsS "$BOT_HEALTHCHECK_URL" >/dev/null
else
  echo "BOT_HEALTHCHECK_URL is not set, skipping healthcheck." >&2
fi

if [[ -n "${DB_HOST:-}" && -n "${DB_PORT:-}" ]]; then
  echo "Checking DB connectivity: $DB_HOST:$DB_PORT"
  nc -z "$DB_HOST" "$DB_PORT"
else
  echo "DB_HOST/DB_PORT not set, skipping DB connectivity check." >&2
fi

if [[ -n "${TELEGRAM_TEST_CHAT_ID:-}" && -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Sending test message to Telegram chat: $TELEGRAM_TEST_CHAT_ID"
  curl -fsS \
    -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_TEST_CHAT_ID}" \
    --data-urlencode "text=Smoke test: bot is alive." \
    >/dev/null
else
  echo "TELEGRAM_TEST_CHAT_ID or TELEGRAM_BOT_TOKEN not set, skipping test message." >&2
fi

echo "Smoke tests completed."
