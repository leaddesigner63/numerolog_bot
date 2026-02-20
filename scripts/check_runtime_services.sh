#!/usr/bin/env bash
set -euo pipefail

API_SERVICE_NAME="${API_SERVICE_NAME:-numerolog-api.service}"
BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-numerolog-bot.service}"
SERVICE_NAMES_OVERRIDE="${SERVICE_NAMES_OVERRIDE:-}"

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
