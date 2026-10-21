#!/usr/bin/env bash
# Thin wrapper kept for muscle memory; the logic lives in scripts/lab_db.py (no psql needed).
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/lab_db.py "$@"
