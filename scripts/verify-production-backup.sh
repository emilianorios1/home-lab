#!/usr/bin/env bash
set -Eeuo pipefail

config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
prod_env="${config_dir}/prod.env"

if (( $# > 1 )); then
    echo "Usage: $0 [backup.dump]" >&2
    exit 2
fi

if (( $# == 1 )); then
    backup_path="$1"
else
    if [[ ! -f "$prod_env" ]]; then
        echo "Missing $prod_env; run scripts/install-production.sh first" >&2
        exit 1
    fi
    backup_dir="$(
        awk '
            index($0, "HOME_LAB_BACKUP_DIR=") == 1 {
                value = substr($0, length("HOME_LAB_BACKUP_DIR=") + 1)
            }
            END { print value }
        ' "$prod_env"
    )"
    backup_dir="${backup_dir:-${HOME}/.local/share/home-lab/backups}"
    shopt -s nullglob
    backups=("$backup_dir"/home-lab-prod-????????T??????Z.dump)
    if (( ${#backups[@]} == 0 )); then
        echo "No production backup found in $backup_dir" >&2
        exit 1
    fi
    backup_path="${backups[${#backups[@]} - 1]}"
fi

if [[ ! -s "$backup_path" ]]; then
    echo "Backup is missing or empty: $backup_path" >&2
    exit 1
fi

container_name="home-lab-backup-verify-$$-${RANDOM}"
cleanup() {
    docker rm --force "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --rm \
    --name "$container_name" \
    --network none \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev \
    --env POSTGRES_HOST_AUTH_METHOD=trust \
    postgres:17-alpine >/dev/null

ready=false
for _ in {1..30}; do
    if docker exec "$container_name" \
        pg_isready --username postgres --dbname postgres >/dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 1
done
if [[ "$ready" != true ]]; then
    echo "Temporary PostgreSQL did not become ready" >&2
    exit 1
fi

docker exec "$container_name" \
    createdb --username postgres home_lab_restore_check
docker exec -i "$container_name" \
    pg_restore \
        --username postgres \
        --dbname home_lab_restore_check \
        --no-owner \
        --no-privileges \
        --exit-on-error \
    < "$backup_path"

has_bronze="$(
    docker exec "$container_name" \
        psql \
            --username postgres \
            --dbname home_lab_restore_check \
            --tuples-only \
            --no-align \
            --command="select to_regnamespace('bronze') is not null"
)"
if [[ "$has_bronze" != "t" ]]; then
    echo "Restored backup has no Bronze schema" >&2
    exit 1
fi

echo "Backup restore verified: $(basename "$backup_path")"
