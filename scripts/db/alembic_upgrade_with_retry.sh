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

ALEMBIC_UPGRADE_ATTEMPTS="${ALEMBIC_UPGRADE_ATTEMPTS:-60}"
ALEMBIC_UPGRADE_INTERVAL_SECONDS="${ALEMBIC_UPGRADE_INTERVAL_SECONDS:-5}"
ALEMBIC_RETRY_ON_ANY_ERROR="${ALEMBIC_RETRY_ON_ANY_ERROR:-1}"

is_retryable_alembic_error() {
  # По умолчанию ретраим любую ошибку, чтобы переживать не только recovery PostgreSQL,
  # но и кратковременные сетевые/инфраструктурные сбои.
  if [ "$ALEMBIC_RETRY_ON_ANY_ERROR" = "1" ]; then
    return 0
  fi

  local error_text="$1"
  echo "$error_text" | grep -Eqi \
    'not yet accepting connections|consistent recovery state has not been yet reached|connection refused|could not connect|timeout expired|temporary failure in name resolution'
}

echo "[INFO] Запуск Alembic с ретраями: attempts=$ALEMBIC_UPGRADE_ATTEMPTS, interval=${ALEMBIC_UPGRADE_INTERVAL_SECONDS}s, retry_on_any_error=$ALEMBIC_RETRY_ON_ANY_ERROR"

for ((attempt=1; attempt<=ALEMBIC_UPGRADE_ATTEMPTS; attempt++)); do
  echo "[WAIT] Alembic upgrade attempt $attempt/$ALEMBIC_UPGRADE_ATTEMPTS"
  alembic_log_file="$(mktemp)"
  set +e
  $ALEMBIC_CMD upgrade head >"$alembic_log_file" 2>&1
  alembic_exit_code=$?
  set -e

  if [ "$alembic_exit_code" -eq 0 ]; then
    cat "$alembic_log_file"
    rm -f -- "$alembic_log_file"
    echo "[OK] Alembic upgrade выполнен."
    exit 0
  fi

  alembic_output="$(cat "$alembic_log_file")"
  rm -f -- "$alembic_log_file"
  echo "$alembic_output"

  if ! is_retryable_alembic_error "$alembic_output"; then
    echo "[FAIL] Alembic upgrade завершился неретраебельной ошибкой (exit=$alembic_exit_code)"
    exit "$alembic_exit_code"
  fi

  if [ "$attempt" -lt "$ALEMBIC_UPGRADE_ATTEMPTS" ]; then
    echo "[WAIT] Alembic upgrade не выполнен, повтор через ${ALEMBIC_UPGRADE_INTERVAL_SECONDS}с"
    sleep "$ALEMBIC_UPGRADE_INTERVAL_SECONDS"
  fi
done

echo "[FAIL] Alembic upgrade не выполнен после $ALEMBIC_UPGRADE_ATTEMPTS попыток"
exit 1
