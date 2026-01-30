#!/usr/bin/env bash
set -euo pipefail

required_files=(
  "README.md"
  "docs/technical_spec_v0_2.md"
  "docs/autodeploy.md"
  ".github/workflows/ci.yml"
  ".github/workflows/deploy.yml"
)

for file in "${required_files[@]}"; do
  if [[ ! -f "$file" ]]; then
    echo "Missing required file: $file" >&2
    exit 1
  fi
done

echo "All required files are present."
