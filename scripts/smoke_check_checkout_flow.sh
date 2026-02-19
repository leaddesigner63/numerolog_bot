#!/usr/bin/env bash
set -euo pipefail

# Smoke-check для checkout-at-end флоу.
# Запускает только регрессионные тесты, критичные для новой позиции оплаты.

if command -v pytest >/dev/null 2>&1; then
  PYTEST_CMD=(pytest)
elif command -v python3 >/dev/null 2>&1 && python3 -c "import pytest" >/dev/null 2>&1; then
  PYTEST_CMD=(python3 -m pytest)
elif command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then
  PYTEST_CMD=(python -m pytest)
else
  echo "[smoke_check_checkout_flow] pytest не найден, пробуем установить зависимости автоматически..." >&2

  if command -v python3 >/dev/null 2>&1; then
    python3 -m ensurepip --upgrade >/dev/null 2>&1 || true
    python3 -m pip install -r requirements.txt >/dev/null 2>&1 || python3 -m pip install pytest >/dev/null 2>&1 || true

    if python3 -c "import pytest" >/dev/null 2>&1; then
      PYTEST_CMD=(python3 -m pytest)
    fi
  elif command -v python >/dev/null 2>&1; then
    python -m ensurepip --upgrade >/dev/null 2>&1 || true
    python -m pip install -r requirements.txt >/dev/null 2>&1 || python -m pip install pytest >/dev/null 2>&1 || true

    if python -c "import pytest" >/dev/null 2>&1; then
      PYTEST_CMD=(python -m pytest)
    fi
  fi

  if [ -z "${PYTEST_CMD+x}" ]; then
    echo "[smoke_check_checkout_flow] pytest недоступен даже после попытки автоустановки. Установите зависимости вручную: pip install -r requirements.txt" >&2
    exit 127
  fi
fi

"${PYTEST_CMD[@]}" -q \
  tests/test_payment_screen_transitions.py \
  tests/test_payment_screen_s3.py \
  tests/test_report_job_requires_paid_order.py \
  tests/test_profile_questionnaire_access_guards.py \
  tests/test_start_payload_routing.py \
  tests/test_payment_waiter_restore.py \
  tests/test_screen_s2_checkout_flow.py \
  tests/test_questionnaire_done_refresh.py
