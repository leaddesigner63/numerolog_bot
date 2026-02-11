#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-}"
GIT_REF="${GIT_REF:-}"
ENV_FILE="${ENV_FILE:-}"
SERVICE_NAME="${SERVICE_NAME:-}"
SERVICE_NAMES="${SERVICE_NAMES:-}"

if [ -z "$DEPLOY_PATH" ]; then
  echo "DEPLOY_PATH не задан. Укажите путь к директории проекта на сервере."
  exit 1
fi

if [ ! -d "$DEPLOY_PATH" ]; then
  echo "DEPLOY_PATH не существует: $DEPLOY_PATH"
  exit 1
fi

cd "$DEPLOY_PATH"

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
  "app/assets/screen_images/S15*"
  "app/assets/screen_images/s15*"
)

clean_args=(-fd)
for exclude_pattern in "${clean_excludes[@]}"; do
  clean_args+=("-e" "$exclude_pattern")
done

git clean "${clean_args[@]}"

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

if [ -f scripts/smoke_check_landing.sh ]; then
  bash scripts/smoke_check_landing.sh
else
  echo "scripts/smoke_check_landing.sh не найден, smoke-check пропущен."
fi
