#!/usr/bin/env bash
set -euo pipefail

required_files=(
  "README.md"
  "docs/technical_spec_v0_2.md"
  "docs/autodeploy.md"
  "docs/autodeploy_runbook.md"
  "docs/llm_logging_policy.md"
  "docs/autodeploy_steps.md"
  "config/config.php"
  "config/bootstrap.php"
  "config/README.md"
  ".github/workflows/ci.yml"
  ".github/workflows/deploy.yml"
  "scripts/smoke_test.sh"
  "scripts/migrate.php"
  "storage/migrations/001_init.sql"
)

required_dirs=(
  "bot"
  "domain"
  "storage"
  "llm"
  "pdf"
  "admin"
  "export"
  "config"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

for dir in "${required_dirs[@]}"; do
  if [[ ! -d "$dir" ]]; then
    echo "Missing required directory: $dir" >&2
    exit 1
  fi
done

echo "All required files are present."

bash scripts/smoke_test.sh
