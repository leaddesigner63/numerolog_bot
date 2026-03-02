#!/usr/bin/env bash
set -euo pipefail

bash -n scripts/deploy.sh
bash -n scripts/db/alembic_upgrade_with_retry.sh
PYTHONPATH=. python scripts/fast_checks.py
python scripts/check_landing_content.py
PYTHONPATH=. python -m pytest -q tests/test_redirect_pages_metrika_flow.py
PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py"
