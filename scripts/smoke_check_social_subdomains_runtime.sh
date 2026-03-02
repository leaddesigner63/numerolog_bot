#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=. python scripts/smoke_check_social_subdomains_runtime.py
