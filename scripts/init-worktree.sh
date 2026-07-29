#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${repo_root}/.env"
venv="${repo_root}/.venv"

if [[ ! -f "${repo_root}/.git" ]]; then
    echo "This command is only for linked Git worktrees" >&2
    exit 1
fi

slug="$(
    basename "$repo_root" \
        | tr '[:upper:]_' '[:lower:]-' \
        | tr -cd 'a-z0-9-' \
        | cut -c1-32
)"
if [[ -z "$slug" ]]; then
    echo "Could not derive a safe name from $repo_root" >&2
    exit 1
fi

free_port() {
    python3 -c \
        'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

if [[ ! -f "$env_file" ]]; then
    postgres_port="$(free_port)"
    dashboard_port="$(free_port)"
    while [[ "$dashboard_port" == "$postgres_port" ]]; do
        dashboard_port="$(free_port)"
    done
    db_name="home_lab_${slug//-/_}"
    db_user="$db_name"
    db_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"

    umask 077
    {
        echo "COMPOSE_PROJECT_NAME=home-lab-wt-${slug}"
        echo "HOME_LAB_DEV_IMAGE=home-lab-wt-${slug}:dev"
        echo "HOME_LAB_DEV_POSTGRES_VOLUME=home-lab-wt-${slug}-postgres-data"
        echo "HOME_LAB_DEV_POSTGRES_PORT=${postgres_port}"
        echo "HOME_LAB_DEV_DASHBOARD_PORT=${dashboard_port}"
        echo "DBT_POSTGRES_HOST=127.0.0.1"
        echo "DBT_POSTGRES_PORT=${postgres_port}"
        echo "POSTGRES_DB=${db_name}"
        echo "POSTGRES_USER=${db_user}"
        echo "POSTGRES_PASSWORD=${db_password}"
        echo "DATABASE_URL=postgresql+psycopg://${db_user}:${db_password}@127.0.0.1:${postgres_port}/${db_name}"
        echo "DOCUMENT_STORE_PATH=data/bronze/gmail"
        echo "FINANCIAL_STATEMENT_STORE_PATH=data/bronze/financial-statements"
    } > "$env_file"
    echo "Created isolated worktree configuration at $env_file"
else
    echo "Reusing existing $env_file"
fi

postgres_port="$(
    sed -n 's/^HOME_LAB_DEV_POSTGRES_PORT=//p' "$env_file" | tail -n 1
)"
if [[ -z "$postgres_port" ]]; then
    echo "Missing HOME_LAB_DEV_POSTGRES_PORT in $env_file" >&2
    exit 1
fi
if ! grep -q '^DBT_POSTGRES_HOST=' "$env_file"; then
    echo "DBT_POSTGRES_HOST=127.0.0.1" >> "$env_file"
fi
if ! grep -q '^DBT_POSTGRES_PORT=' "$env_file"; then
    echo "DBT_POSTGRES_PORT=${postgres_port}" >> "$env_file"
fi

if [[ ! -x "${venv}/bin/python" ]]; then
    python3 -m venv "$venv"
fi
"${venv}/bin/pip" install -e "${repo_root}[dev]"

echo "Worktree ready. Start it with scripts/dev-up.sh"
