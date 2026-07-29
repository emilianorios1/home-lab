#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# != 1 )); then
    echo "Usage: $0 <container-image-or-digest>" >&2
    exit 2
fi

image="$1"
if [[ -z "$image" || "$image" == *$'\n'* || "$image" == *$'\r'* ]]; then
    echo "Invalid container image" >&2
    exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
prod_env="${config_dir}/prod.env"
deployment_env="${config_dir}/deployment.env"
previous_env="${config_dir}/deployment.previous.env"
previous_compose="${config_dir}/compose.production.previous.yaml"
compose_command="${config_dir}/production-compose.sh"
lock_file="${config_dir}/deployment.lock"

mkdir -p "$config_dir"
if [[ ! -f "$prod_env" ]]; then
    echo "Missing $prod_env; run scripts/install-production.sh first" >&2
    exit 1
fi

exec 9>"$lock_file"
if ! flock -n 9; then
    echo "Another production deployment is already running" >&2
    exit 1
fi

had_previous=false
if [[ -f "$deployment_env" ]]; then
    had_previous=true
    cp "$deployment_env" "$previous_env"
    cp "${config_dir}/compose.production.yaml" "$previous_compose"
    if "$compose_command" ps --status running --services 2>/dev/null | grep -qx postgres; then
        "${config_dir}/backup-production.sh"
    fi
fi

install -m 0644 "$repo_root/compose.production.yaml" \
    "${config_dir}/compose.production.yaml"
install -m 0755 "$repo_root/scripts/production-compose.sh" "$compose_command"
install -m 0755 "$repo_root/scripts/backup-production.sh" \
    "${config_dir}/backup-production.sh"

umask 077
new_env="$(mktemp "${config_dir}/deployment.env.XXXXXX")"
printf 'HOME_LAB_IMAGE=%s\n' "$image" > "$new_env"
mv "$new_env" "$deployment_env"

rollback() {
    status=$?
    trap - ERR
    if [[ "$had_previous" == true && -f "$previous_env" ]]; then
        echo "Deployment failed; restoring the previously deployed image" >&2
        cp "$previous_env" "$deployment_env"
        cp "$previous_compose" "${config_dir}/compose.production.yaml"
        "$compose_command" up -d --wait --wait-timeout 120 postgres dashboard || true
    fi
    exit "$status"
}
trap rollback ERR

"$compose_command" config --quiet

if [[ "${HOME_LAB_SKIP_PULL:-0}" != "1" ]]; then
    "$compose_command" pull postgres dashboard migrate
fi

"$compose_command" up -d --wait --wait-timeout 120 postgres
"$compose_command" run --rm migrate
"$compose_command" up -d --wait --wait-timeout 180 --remove-orphans dashboard

trap - ERR
rm -f "$previous_env" "$previous_compose"

env_value() {
    local key="$1"
    awk -v key="$key" '
        index($0, key "=") == 1 { value = substr($0, length(key) + 2) }
        END { print value }
    ' "$prod_env"
}
production_bind="$(env_value HOME_LAB_PROD_BIND)"
production_port="$(env_value HOME_LAB_PROD_PORT)"
echo "Production deployed with image $image at ${production_bind:-0.0.0.0}:${production_port:-8501}"
