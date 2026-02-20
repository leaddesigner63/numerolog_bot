#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="python3"
if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
elif [ -x "${REPO_ROOT}/venv/bin/python" ]; then
  PYTHON_BIN="${REPO_ROOT}/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
fi

if [ -z "${PYTHON_BIN}" ] || [ ! -x "${PYTHON_BIN}" ]; then
  echo "[smoke_report_job] Python не найден. Smoke-check report job завершён с ошибкой."
  exit 1
fi

PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}" \
  "${PYTHON_BIN}" "${REPO_ROOT}/scripts/smoke_check_report_job_completion.py"
