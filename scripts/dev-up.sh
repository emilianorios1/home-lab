#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${repo_root}/.env"

if [[ ! -f "$env_file" ]]; then
    echo "Missing $env_file; copy .env.example to .env first" >&2
    exit 1
fi

compose() {
    docker compose --env-file "$env_file" -f "${repo_root}/docker-compose.yml" "$@"
}

compose build dashboard
compose up -d --wait --wait-timeout 120 postgres
compose run --rm migrate
compose up -d --wait --wait-timeout 180 dashboard

echo "Development is ready at $(compose port dashboard 8501)"
