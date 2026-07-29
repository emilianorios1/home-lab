#!/usr/bin/env bash
set -Eeuo pipefail

config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
compose_file="${config_dir}/compose.production.yaml"
prod_env="${config_dir}/prod.env"
deployment_env="${config_dir}/deployment.env"

for required_file in "$compose_file" "$prod_env" "$deployment_env"; do
    if [[ ! -f "$required_file" ]]; then
        echo "Missing production file: $required_file" >&2
        exit 1
    fi
done

exec docker compose \
    --env-file "$prod_env" \
    --env-file "$deployment_env" \
    -f "$compose_file" \
    "$@"
