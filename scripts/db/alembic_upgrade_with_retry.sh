#!/usr/bin/env bash
set -euo pipefail

# Универсальный раннер миграций Alembic с ретраями.
# Можно использовать в deploy.sh и в systemd ExecStartPre.

if [ ! -f alembic.ini ]; then
  echo "[SKIP] alembic.ini не найден, миграции Alembic пропущены."
  exit 0
fi

ALEMBIC_CMD="${ALEMBIC_CMD:-alembic}"
if [ "$ALEMBIC_CMD" = "alembic" ]; then
  if [ -x .venv/bin/alembic ]; then
    ALEMBIC_CMD=".venv/bin/alembic"
  elif [ -x venv/bin/alembic ]; then
    ALEMBIC_CMD="venv/bin/alembic"
  fi
fi

if ! command -v "${ALEMBIC_CMD%% *}" >/dev/null 2>&1 && [ ! -x "${ALEMBIC_CMD%% *}" ]; then
  echo "[FAIL] Команда Alembic не найдена: $ALEMBIC_CMD"
  exit 1
fi

ALEMBIC_UPGRADE_ATTEMPTS="${ALEMBIC_UPGRADE_ATTEMPTS:-20}"
ALEMBIC_UPGRADE_INTERVAL_SECONDS="${ALEMBIC_UPGRADE_INTERVAL_SECONDS:-3}"

echo "[INFO] Запуск Alembic с ретраями: attempts=$ALEMBIC_UPGRADE_ATTEMPTS, interval=${ALEMBIC_UPGRADE_INTERVAL_SECONDS}s"

for ((attempt=1; attempt<=ALEMBIC_UPGRADE_ATTEMPTS; attempt++)); do
  echo "[WAIT] Alembic upgrade attempt $attempt/$ALEMBIC_UPGRADE_ATTEMPTS"
  if $ALEMBIC_CMD upgrade head; then
    echo "[OK] Alembic upgrade выполнен."
    exit 0
  fi

  if [ "$attempt" -lt "$ALEMBIC_UPGRADE_ATTEMPTS" ]; then
    echo "[WAIT] Alembic upgrade не выполнен, повтор через ${ALEMBIC_UPGRADE_INTERVAL_SECONDS}с"
    sleep "$ALEMBIC_UPGRADE_INTERVAL_SECONDS"
  fi
done

echo "[FAIL] Alembic upgrade не выполнен после $ALEMBIC_UPGRADE_ATTEMPTS попыток"
exit 1
