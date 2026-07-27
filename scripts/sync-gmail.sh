#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

exec flock --nonblock data/gmail-sync.lock \
  .venv/bin/home-lab sync-gmail
