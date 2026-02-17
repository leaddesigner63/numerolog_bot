#!/usr/bin/env bash
set -euo pipefail

bash -n scripts/deploy.sh
PYTHONPATH=. python scripts/fast_checks.py
python scripts/check_landing_content.py
PYTHONPATH=. python -m unittest discover -s tests -p "test_*.py"
