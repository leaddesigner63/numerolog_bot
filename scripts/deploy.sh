#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-}"
GIT_REF="${GIT_REF:-}"
ENV_FILE="${ENV_FILE:-}"
SERVICE_NAME="${SERVICE_NAME:-}"
SERVICE_NAMES="${SERVICE_NAMES:-}"
PRESERVE_PATHS="${PRESERVE_PATHS:-app/assets/screen_images app/assets/pdf}"

if [ -z "$DEPLOY_PATH" ]; then
  echo "DEPLOY_PATH не задан. Укажите путь к директории проекта на сервере."
  exit 1
fi

if [ ! -d "$DEPLOY_PATH" ]; then
  echo "DEPLOY_PATH не существует: $DEPLOY_PATH"
  exit 1
fi

cd "$DEPLOY_PATH"

backup_root=""
if [ -n "$PRESERVE_PATHS" ]; then
  backup_root="$(mktemp -d)"
  IFS=' ' read -r -a preserve_paths <<< "$PRESERVE_PATHS"
  for preserve_path in "${preserve_paths[@]}"; do
    [ -z "$preserve_path" ] && continue
    if [ -e "$preserve_path" ]; then
      mkdir -p "$backup_root/$(dirname "$preserve_path")"
      cp -a "$preserve_path" "$backup_root/$preserve_path"
    fi
  done
fi

if [ -z "$GIT_REF" ]; then
  if CURRENT_BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null); then
    GIT_REF="origin/${CURRENT_BRANCH}"
  else
    GIT_REF="origin/main"
  fi
fi

git fetch --all --prune
git reset --hard "$GIT_REF"

# Не удаляем важные локальные файлы (например, .env и каталоги с данными).
# Паттерны собираем в массив, чтобы shell не раскрывал маски до передачи в git clean.

# Явные паттерны для S15/S15_* сохраняем в таком виде для прозрачности деплоя:
# -e app/assets/screen_images/S15
# -e app/assets/screen_images/S15_*
clean_excludes=(
  ".env"
  ".env.*"
  "venv"
  ".venv"
  ".python-version"
  "data"
  "storage"
  "uploads"
  "logs"
  "app/assets/screen_images/S15"
  "app/assets/screen_images/S15_*"
  "app/assets/screen_images/S15*"
  "app/assets/screen_images/s15*"
)

clean_args=(-fd)
for exclude_pattern in "${clean_excludes[@]}"; do
  clean_args+=("-e" "$exclude_pattern")
done

git clean "${clean_args[@]}"

if [ -n "$backup_root" ]; then
  for preserve_path in "${preserve_paths[@]}"; do
    [ -z "$preserve_path" ] && continue
    if [ -e "$backup_root/$preserve_path" ]; then
      mkdir -p "$(dirname "$preserve_path")"
      rm -rf -- "$preserve_path"
      cp -a "$backup_root/$preserve_path" "$preserve_path"
    fi
  done
  rm -rf -- "$backup_root"
fi

if [ -f requirements.txt ]; then
  if [ -x .venv/bin/pip ]; then
    .venv/bin/pip install -r requirements.txt
  elif [ -x venv/bin/pip ]; then
    venv/bin/pip install -r requirements.txt
  fi
fi

if [ -n "$ENV_FILE" ] && [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

if [ -f alembic.ini ]; then
  ALEMBIC_CMD="alembic"
  if [ -x .venv/bin/alembic ]; then
    ALEMBIC_CMD=".venv/bin/alembic"
  elif [ -x venv/bin/alembic ]; then
    ALEMBIC_CMD="venv/bin/alembic"
  fi
  if [ -x "$ALEMBIC_CMD" ]; then
    "$ALEMBIC_CMD" upgrade head
  fi
fi

if [ -f scripts/migrate.php ]; then
  php scripts/migrate.php
fi

if [ -f scripts/generate_sitemap.py ]; then
  SITEMAP_PYTHON="python3"
  if [ -x .venv/bin/python ]; then
    SITEMAP_PYTHON=".venv/bin/python"
  elif [ -x venv/bin/python ]; then
    SITEMAP_PYTHON="venv/bin/python"
  fi
  "$SITEMAP_PYTHON" scripts/generate_sitemap.py
fi

SERVICES="${SERVICE_NAMES:-$SERVICE_NAME}"
if [ -z "$SERVICES" ]; then
  echo "SERVICE_NAME или SERVICE_NAMES должны быть заданы."
  exit 1
fi

SYSTEMCTL="systemctl"
if [ "${EUID:-$(id -u)}" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SYSTEMCTL="sudo systemctl"
fi

read -r -a services <<< "$SERVICES"
if [ "${#services[@]}" -eq 0 ]; then
  echo "Не удалось разобрать список сервисов: $SERVICES"
  exit 1
fi

$SYSTEMCTL daemon-reload
$SYSTEMCTL restart -- "${services[@]}"
$SYSTEMCTL --no-pager --full status -- "${services[@]}" | head -n 80

if [ -x scripts/check_runtime_services.sh ]; then
  API_SERVICE_NAME="${API_SERVICE_NAME:-numerolog-api.service}" \
  BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-numerolog-bot.service}" \
  SERVICE_NAMES_OVERRIDE="$SERVICES" \
  bash scripts/check_runtime_services.sh
else
  echo "scripts/check_runtime_services.sh не найден или не исполняемый."
  exit 1
fi

if [ -f scripts/smoke_check_landing.sh ]; then
  bash scripts/smoke_check_landing.sh
else
  echo "scripts/smoke_check_landing.sh не найден, smoke-check пропущен."
fi

smoke_status=0
if [ -x scripts/smoke_check_report_job_completion.sh ]; then
  echo "Запуск smoke-check paid order -> ReportJob -> COMPLETED (этап после деплоя)"
  set +e
  bash scripts/smoke_check_report_job_completion.sh
  smoke_status=$?
  set -e
  if [ "$smoke_status" -ne 0 ]; then
    echo "Smoke-check ReportJob завершился с ошибкой (код=$smoke_status). Переходим к обязательной очистке после деплоя."
  fi
else
  echo "scripts/smoke_check_report_job_completion.sh не найден или не исполняемый."
  exit 1
fi

cleanup_before_line=""
cleanup_after_line=""
if [ -x scripts/smoke_check_report_job_completion.sh ]; then
  echo "Запуск обязательной cleanup-only очистки smoke-данных после деплоя"
  cleanup_before_log="$(mktemp)"
  set +e
  bash scripts/smoke_check_report_job_completion.sh cleanup-only 2>&1 | tee "$cleanup_before_log"
  cleanup_status=${PIPESTATUS[0]}
  set -e
  cleanup_before_line="$(awk '/stage=cleanup_targets/{line=$0} END{print line}' "$cleanup_before_log")"
  rm -f -- "$cleanup_before_log"

  if [ "$cleanup_status" -ne 0 ]; then
    echo "ОШИБКА: cleanup-only очистка после деплоя завершилась неуспешно (код=$cleanup_status)."
    exit 1
  fi

  cleanup_after_log="$(mktemp)"
  set +e
  bash scripts/smoke_check_report_job_completion.sh cleanup-only 2>&1 | tee "$cleanup_after_log"
  cleanup_verify_status=${PIPESTATUS[0]}
  set -e
  cleanup_after_line="$(awk '/stage=cleanup_targets/{line=$0} END{print line}' "$cleanup_after_log")"
  rm -f -- "$cleanup_after_log"

  if [ "$cleanup_verify_status" -ne 0 ]; then
    echo "ОШИБКА: проверка cleanup-only после деплоя завершилась неуспешно (код=$cleanup_verify_status)."
    exit 1
  fi

  before_counts="${cleanup_before_line#*stage=cleanup_targets }"
  after_counts="${cleanup_after_line#*stage=cleanup_targets }"
  [ "$before_counts" = "$cleanup_before_line" ] && before_counts="unknown"
  [ "$after_counts" = "$cleanup_after_line" ] && after_counts="unknown"
  echo "Итог cleanup smoke-записей после деплоя: до очистки -> ${before_counts}; после очистки -> ${after_counts}."
else
  echo "scripts/smoke_check_report_job_completion.sh не найден или не исполняемый (не удалось выполнить cleanup-only после деплоя)."
  exit 1
fi

if [ "$smoke_status" -ne 0 ]; then
  echo "ОШИБКА: smoke-check paid order -> ReportJob -> COMPLETED завершился с ошибкой (код=$smoke_status)."
  exit "$smoke_status"
fi

if [ -n "${WEBMASTER_PING_SCRIPT:-}" ] && [ -x "${WEBMASTER_PING_SCRIPT}" ]; then
  "$WEBMASTER_PING_SCRIPT" || echo "Пинг вебмастеров завершился с ошибкой (продолжаем деплой)."
elif [ -x scripts/post_release_ping.sh ]; then
  bash scripts/post_release_ping.sh || echo "Скрипт scripts/post_release_ping.sh завершился с ошибкой (продолжаем деплой)."
elif [ -n "${WEBMASTER_PING_URLS:-}" ] && command -v curl >/dev/null 2>&1; then
  IFS=',' read -r -a ping_urls <<< "$WEBMASTER_PING_URLS"
  for ping_url in "${ping_urls[@]}"; do
    ping_url="${ping_url## }"
    ping_url="${ping_url%% }"
    [ -z "$ping_url" ] && continue
    curl --silent --show-error --max-time 15 "$ping_url" >/dev/null       || echo "Не удалось пинговать: $ping_url"
  done
else
  echo "[WARNING] Пост-релизный SEO-пинг пропущен."
  echo "[WARNING] Чтобы включить индексацию после деплоя, выполните одно из действий:"
  echo "[WARNING] 1) задайте секрет WEBMASTER_PING_URLS в CI (URL через запятую),"
  echo "[WARNING] 2) или задайте WEBMASTER_PING_SCRIPT и разместите исполняемый скрипт на сервере."
fi

DEPLOY_SUCCESS_MARKER="${DEPLOY_SUCCESS_MARKER:-$DEPLOY_PATH/.last_deploy_success}"
printf '%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" > "$DEPLOY_SUCCESS_MARKER"
echo "[OK] Деплой успешно завершен. Маркер: $DEPLOY_SUCCESS_MARKER"
