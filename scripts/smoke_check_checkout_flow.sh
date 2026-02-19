#!/usr/bin/env bash
set -euo pipefail

# Smoke-check для checkout-at-end флоу.
# Запускает только регрессионные тесты, критичные для новой позиции оплаты.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REQ_FILE="${REPO_ROOT}/requirements.txt"

if command -v pytest >/dev/null 2>&1; then
  PYTEST_CMD=(pytest)
elif command -v python3 >/dev/null 2>&1 && python3 -c "import pytest" >/dev/null 2>&1; then
  PYTEST_CMD=(python3 -m pytest)
elif command -v python >/dev/null 2>&1 && python -c "import pytest" >/dev/null 2>&1; then
  PYTEST_CMD=(python -m pytest)
else
  echo "[smoke_check_checkout_flow] pytest не найден, пробуем установить зависимости автоматически..." >&2

  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
  else
    echo "[smoke_check_checkout_flow] Python не найден. Установите Python 3 и зависимости вручную." >&2
    exit 127
  fi

  VENV_DIR="${REPO_ROOT}/.venv_smoke_checkout"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}" >/dev/null 2>&1 || true

  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    "${PYTHON_BIN}" -m ensurepip --upgrade >/dev/null 2>&1 || true
    "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null 2>&1 || true

    if [ -f "${REQ_FILE}" ]; then
      "${PYTHON_BIN}" -m pip install -r "${REQ_FILE}" >/dev/null 2>&1 || true
    fi
    "${PYTHON_BIN}" -m pip install pytest >/dev/null 2>&1 || true

    if "${PYTHON_BIN}" -c "import pytest" >/dev/null 2>&1; then
      PYTEST_CMD=("${PYTHON_BIN}" -m pytest)
    fi
  else
    "${VENV_DIR}/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true

    if [ -f "${REQ_FILE}" ]; then
      "${VENV_DIR}/bin/python" -m pip install -r "${REQ_FILE}" >/dev/null 2>&1 || true
    fi
    "${VENV_DIR}/bin/python" -m pip install pytest >/dev/null 2>&1 || true

    if "${VENV_DIR}/bin/python" -c "import pytest" >/dev/null 2>&1; then
      PYTEST_CMD=("${VENV_DIR}/bin/python" -m pytest)
    fi
  fi

  if [ -z "${PYTEST_CMD+x}" ]; then
    echo "[smoke_check_checkout_flow] pytest недоступен даже после попытки автоустановки. Установите зависимости вручную: pip install -r requirements.txt" >&2
    exit 127
  fi
fi

"${PYTEST_CMD[@]}" -q \
  "${REPO_ROOT}/tests/test_payment_screen_transitions.py" \
  "${REPO_ROOT}/tests/test_payment_screen_s3.py" \
  "${REPO_ROOT}/tests/test_report_job_requires_paid_order.py" \
  "${REPO_ROOT}/tests/test_profile_questionnaire_access_guards.py" \
  "${REPO_ROOT}/tests/test_start_payload_routing.py" \
  "${REPO_ROOT}/tests/test_payment_waiter_restore.py" \
  "${REPO_ROOT}/tests/test_screen_s2_checkout_flow.py" \
  "${REPO_ROOT}/tests/test_questionnaire_done_refresh.py"
