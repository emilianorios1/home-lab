#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p data
exec flock -n data/siat-tgi-sync.lock .venv/bin/home-lab sync-siat-tgi
