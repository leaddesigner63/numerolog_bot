#!/usr/bin/env bash
set -euo pipefail

bash -n scripts/deploy.sh
PYTHONPATH=. python scripts/fast_checks.py
