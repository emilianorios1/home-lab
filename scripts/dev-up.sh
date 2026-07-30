#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${repo_root}/.env"

if [[ ! -f "$env_file" ]]; then
    if [[ -f "${repo_root}/.git" ]]; then
        echo "Missing $env_file; run scripts/init-worktree.sh first" >&2
    else
        echo "Missing $env_file; copy .env.example to .env first" >&2
    fi
    exit 1
fi

compose() {
    docker compose --env-file "$env_file" -f "${repo_root}/docker-compose.yml" "$@"
}

compose build dashboard
compose up -d --wait --wait-timeout 120 postgres

if [[ -f "${repo_root}/.git" ]]; then
    # Expansion is intentionally performed inside the PostgreSQL container.
    # shellcheck disable=SC2016
    has_home_lab_schema="$(
        compose exec -T postgres sh -ec \
            'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" \
                --tuples-only --no-align \
                --command="select to_regnamespace('\''bronze'\'') is not null"'
    )"
    if [[ "$has_home_lab_schema" != "t" ]]; then
        backup_path="$("${repo_root}/scripts/backup-production.sh")"
        if [[ ! -s "$backup_path" ]]; then
            echo "Production backup is missing or empty: $backup_path" >&2
            exit 1
        fi
        echo "Restoring current production snapshot into the worktree database"
        # Expansion is intentionally performed inside the PostgreSQL container.
        # shellcheck disable=SC2016
        compose exec -T postgres sh -ec \
            'exec pg_restore --username="$POSTGRES_USER" \
                --dbname="$POSTGRES_DB" --no-owner --no-privileges \
                --single-transaction --exit-on-error' \
            < "$backup_path"
    fi
fi

compose run --rm migrate
compose up -d --wait --wait-timeout 180 dashboard sync-runner

echo "Development is ready at $(compose port dashboard 8501)"
