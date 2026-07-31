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

read -r -s -p "Nueva clave de Operaciones: " password
echo
if [[ -z "$password" ]]; then
    echo "The password cannot be empty" >&2
    exit 1
fi

escaped_password="${password//\\/\\\\}"
escaped_password="${escaped_password//\'/\\\'}"
temporary_env="$(mktemp "${config_dir}/prod.env.XXXXXX")"
trap 'rm -f "$temporary_env"' EXIT

found=false
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == HOME_LAB_OPERATIONS_PASSWORD=* ]]; then
        printf "HOME_LAB_OPERATIONS_PASSWORD='%s'\n" "$escaped_password" >> "$temporary_env"
        found=true
    else
        printf '%s\n' "$line" >> "$temporary_env"
    fi
done < "$prod_env"

if [[ "$found" == false ]]; then
    printf "\nHOME_LAB_OPERATIONS_PASSWORD='%s'\n" "$escaped_password" >> "$temporary_env"
fi

chmod --reference="$prod_env" "$temporary_env"
mv "$temporary_env" "$prod_env"
trap - EXIT

echo "Clave actualizada. Recreando el dashboard…"
"$compose_command" up -d --force-recreate dashboard
