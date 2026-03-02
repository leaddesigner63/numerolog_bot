#!/usr/bin/env bash
set -euo pipefail

BASE_DOMAIN="${SOCIAL_SUBDOMAIN_BASE_DOMAIN:-aireadu.ru}"
COUNTER_ID="${SOCIAL_SUBDOMAIN_METRIKA_COUNTER_ID:-106884182}"
TARGET_EVENT="${SOCIAL_SUBDOMAIN_TARGET_EVENT:-bridge_redirect}"
SUBDOMAINS=(ig vk yt)

for subdomain in "${SUBDOMAINS[@]}"; do
  url="https://${subdomain}.${BASE_DOMAIN}/"
  echo "[INFO] Проверка ${url}"

  status_code="$(curl -sS -o /dev/null -w '%{http_code}' "$url")"
  if [ "$status_code" != "200" ]; then
    echo "[FAIL] Ожидался HTTP 200 для ${url}, получен ${status_code}"
    exit 1
  fi

  body="$(curl -sS "$url")"

  if ! printf '%s' "$body" | grep -Fq "ym(${COUNTER_ID}, \"init\""; then
    echo "[FAIL] На ${url} не найден вызов инициализации Метрики ym(${COUNTER_ID}, \"init\""
    exit 1
  fi

  if ! printf '%s' "$body" | grep -Fq "\"reachGoal\", \"${TARGET_EVENT}\""; then
    echo "[FAIL] На ${url} не найдено целевое bridge-событие \"reachGoal\", \"${TARGET_EVENT}\""
    exit 1
  fi

  echo "[OK] ${url}: HTTP 200, ym-init и bridge-событие присутствуют"
done

echo "[OK] Все социальные поддомены прошли smoke-проверку"
