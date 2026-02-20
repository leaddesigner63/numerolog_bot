#!/usr/bin/env bash
set -euo pipefail

API_SERVICE_NAME="${API_SERVICE_NAME:-numerolog-api.service}"
BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-numerolog-bot.service}"
SERVICE_NAMES_OVERRIDE="${SERVICE_NAMES_OVERRIDE:-}"
RUNTIME_API_HEALTHCHECK_URL="${RUNTIME_API_HEALTHCHECK_URL:-http://127.0.0.1:8000/health}"
RUNTIME_API_HEALTHCHECK_ATTEMPTS="${RUNTIME_API_HEALTHCHECK_ATTEMPTS:-20}"
RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS="${RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS:-2}"

SYSTEMCTL="systemctl"
if [ "${EUID:-$(id -u)}" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SYSTEMCTL="sudo systemctl"
fi

services=()
if [ -n "$SERVICE_NAMES_OVERRIDE" ]; then
  read -r -a services <<< "$SERVICE_NAMES_OVERRIDE"
else
  services=("$API_SERVICE_NAME" "$BOT_SERVICE_NAME")
fi

if [ "${#services[@]}" -eq 0 ]; then
  echo "Список сервисов для проверки пуст."
  exit 1
fi

failed=0
for service in "${services[@]}"; do
  [ -z "$service" ] && continue
  if $SYSTEMCTL is-active --quiet "$service"; then
    echo "[OK] Сервис активен: $service"
  else
    echo "[FAIL] Сервис неактивен: $service"
    $SYSTEMCTL --no-pager --full status "$service" | head -n 60 || true
    failed=1
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "Проверка рантайм-сервисов завершилась ошибкой."
  exit 1
fi

echo "Проверка рантайм-сервисов успешно завершена."

if command -v curl >/dev/null 2>&1; then
  health_ok=0
  attempts="${RUNTIME_API_HEALTHCHECK_ATTEMPTS}"
  interval_seconds="${RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS}"
  for ((attempt=1; attempt<=attempts; attempt++)); do
    if curl --silent --show-error --fail --max-time 5 "$RUNTIME_API_HEALTHCHECK_URL" >/dev/null; then
      echo "[OK] API healthcheck доступен: $RUNTIME_API_HEALTHCHECK_URL"
      health_ok=1
      break
    fi
    echo "[WAIT] API healthcheck недоступен ($attempt/$attempts): $RUNTIME_API_HEALTHCHECK_URL"
    sleep "$interval_seconds"
  done

  if [ "$health_ok" -ne 1 ]; then
    echo "[FAIL] API healthcheck не прошёл: $RUNTIME_API_HEALTHCHECK_URL"
    for service in "${services[@]}"; do
      [ -z "$service" ] && continue
      $SYSTEMCTL --no-pager --full status "$service" | head -n 80 || true
    done
    exit 1
  fi
else
  echo "[WARNING] curl не найден, API healthcheck пропущен."
fi
