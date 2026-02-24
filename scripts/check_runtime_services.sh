#!/usr/bin/env bash
set -euo pipefail

API_SERVICE_NAME="${API_SERVICE_NAME:-numerolog-api.service}"
BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-numerolog-bot.service}"
SERVICE_NAMES_OVERRIDE="${SERVICE_NAMES_OVERRIDE:-}"
RUNTIME_API_READINESS_URL="${RUNTIME_API_READINESS_URL:-${RUNTIME_API_HEALTHCHECK_URL:-http://127.0.0.1:8000/health/ready}}"
RUNTIME_API_READINESS_ATTEMPTS="${RUNTIME_API_READINESS_ATTEMPTS:-${RUNTIME_API_HEALTHCHECK_ATTEMPTS:-20}}"
RUNTIME_API_READINESS_INTERVAL_SECONDS="${RUNTIME_API_READINESS_INTERVAL_SECONDS:-${RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS:-2}}"
RUNTIME_ADMIN_URL="${RUNTIME_ADMIN_URL:-http://127.0.0.1:8000/admin}"
RUNTIME_ADMIN_DB_READY_URL="${RUNTIME_ADMIN_DB_READY_URL:-http://127.0.0.1:8000/admin/ready}"

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
  readiness_ok=0
  attempts="${RUNTIME_API_READINESS_ATTEMPTS}"
  interval_seconds="${RUNTIME_API_READINESS_INTERVAL_SECONDS}"
  for ((attempt=1; attempt<=attempts; attempt++)); do
    if curl --silent --show-error --fail --max-time 5 "$RUNTIME_API_READINESS_URL" >/dev/null; then
      echo "[OK] API readiness доступен: $RUNTIME_API_READINESS_URL"
      readiness_ok=1
      break
    fi
    echo "[WAIT] API readiness недоступен ($attempt/$attempts): $RUNTIME_API_READINESS_URL"
    sleep "$interval_seconds"
  done

  if [ "$readiness_ok" -ne 1 ]; then
    echo "[FAIL] API readiness не прошёл: $RUNTIME_API_READINESS_URL"
    for service in "${services[@]}"; do
      [ -z "$service" ] && continue
      $SYSTEMCTL --no-pager --full status "$service" | head -n 80 || true
    done
    exit 1
  fi

  admin_http_code="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}" --max-time 5 "$RUNTIME_ADMIN_URL" || true)"
  if [ "$admin_http_code" = "200" ] || [ "$admin_http_code" = "401" ]; then
    echo "[OK] Admin route smoke-check доступен: $RUNTIME_ADMIN_URL (HTTP $admin_http_code)"
  else
    echo "[FAIL] Admin route smoke-check не прошёл: $RUNTIME_ADMIN_URL (HTTP ${admin_http_code:-unknown})"
    exit 1
  fi

  if curl --silent --show-error --fail --max-time 5 "$RUNTIME_ADMIN_DB_READY_URL" | grep -q '"status":"ready"'; then
    echo "[OK] Admin DB readiness доступен: $RUNTIME_ADMIN_DB_READY_URL"
  else
    echo "[FAIL] Admin DB readiness не прошёл: $RUNTIME_ADMIN_DB_READY_URL"
    exit 1
  fi
else
  echo "[WARNING] curl не найден, runtime readiness/smoke-check пропущены."
fi
