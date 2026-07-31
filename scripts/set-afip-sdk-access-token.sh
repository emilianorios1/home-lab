#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# != 0 )); then
    echo "Usage: $0" >&2
    exit 2
fi

config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
prod_env="${config_dir}/prod.env"
compose_command="${config_dir}/production-compose.sh"

if [[ ! -f "$prod_env" || ! -x "$compose_command" ]]; then
    echo "Missing production configuration; run scripts/install-production.sh first" >&2
    exit 1
fi

read -r -s -p "Nuevo access token de Afip SDK: " access_token
echo
if [[ -z "$access_token" ]]; then
    echo "The access token cannot be empty" >&2
    exit 1
fi

escaped_access_token="${access_token//\\/\\\\}"
escaped_access_token="${escaped_access_token//\'/\\\'}"
temporary_env="$(mktemp "${config_dir}/prod.env.XXXXXX")"
trap 'rm -f "$temporary_env"' EXIT

found=false
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == AFIP_SDK_ACCESS_TOKEN=* ]]; then
        printf "AFIP_SDK_ACCESS_TOKEN='%s'\n" "$escaped_access_token" >> "$temporary_env"
        found=true
    else
        printf '%s\n' "$line" >> "$temporary_env"
    fi
done < "$prod_env"

if [[ "$found" == false ]]; then
    printf "\nAFIP_SDK_ACCESS_TOKEN='%s'\n" "$escaped_access_token" >> "$temporary_env"
fi

chmod 600 "$temporary_env"
mv "$temporary_env" "$prod_env"
trap - EXIT

echo "Token actualizado. Recreando el dashboard…"
"$compose_command" up -d --force-recreate dashboard
