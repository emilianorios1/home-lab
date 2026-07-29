#!/usr/bin/env bash
set -Eeuo pipefail

config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
compose_command="${config_dir}/production-compose.sh"
prod_env="${config_dir}/prod.env"

if [[ ! -x "$compose_command" || ! -f "$prod_env" ]]; then
    echo "Production is not installed in $config_dir" >&2
    exit 1
fi

env_value() {
    local key="$1"
    awk -v key="$key" '
        index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
        END { print value }
    ' "$prod_env"
}

backup_dir="$(env_value HOME_LAB_BACKUP_DIR)"
backup_dir="${backup_dir:-${HOME}/.local/share/home-lab/backups}"
retention_days="$(env_value HOME_LAB_BACKUP_RETENTION_DAYS)"
retention_days="${retention_days:-14}"

if [[ ! "$retention_days" =~ ^[0-9]+$ ]] || (( retention_days < 1 )); then
    echo "HOME_LAB_BACKUP_RETENTION_DAYS must be a positive integer" >&2
    exit 1
fi

if ! "$compose_command" ps --status running --services | grep -qx postgres; then
    echo "Production PostgreSQL is not running; backup skipped" >&2
    exit 1
fi

mkdir -p "$backup_dir"
umask 077
timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
final_path="${backup_dir}/home-lab-prod-${timestamp}.dump"
temporary_path="${final_path}.partial"

cleanup() {
    rm -f "$temporary_path"
}
trap cleanup EXIT

# Expansion is intentionally performed inside the PostgreSQL container.
# shellcheck disable=SC2016
"$compose_command" exec -T postgres sh -ec \
    'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --compress=9' \
    > "$temporary_path"

if [[ ! -s "$temporary_path" ]]; then
    echo "PostgreSQL produced an empty backup" >&2
    exit 1
fi

"$compose_command" exec -T postgres pg_restore --list < "$temporary_path" >/dev/null
mv "$temporary_path" "$final_path"
trap - EXIT

find "$backup_dir" -maxdepth 1 -type f \
    -name 'home-lab-prod-????????T??????Z.dump' \
    -mtime "+${retention_days}" -delete

echo "$final_path"
