#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
config_dir="${HOME_LAB_CONFIG_DIR:-${config_home}/home-lab}"
data_dir="${data_home}/home-lab/production"
secrets_dir="${config_dir}/secrets"
backup_dir="${data_home}/home-lab/backups"
prod_env="${config_dir}/prod.env"
image="${1:-home-lab:local}"
production_bind="${HOME_LAB_PROD_BIND:-0.0.0.0}"
production_port="${HOME_LAB_PROD_PORT:-8501}"

mkdir -p "$config_dir" "$data_dir" "$secrets_dir" "$backup_dir"
chmod 700 "$config_dir" "$secrets_dir"

if [[ ! -f "$prod_env" ]]; then
    umask 077
    password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    cat > "$prod_env" <<EOF
POSTGRES_DB=home_lab_prod
POSTGRES_USER=home_lab_prod
POSTGRES_PASSWORD=${password}
HOME_LAB_PROD_BIND=${production_bind}
HOME_LAB_PROD_PORT=${production_port}
HOME_LAB_PROD_DATA_DIR=${data_dir}
HOME_LAB_PROD_SECRETS_DIR=${secrets_dir}
HOME_LAB_BACKUP_DIR=${backup_dir}
HOME_LAB_BACKUP_RETENTION_DAYS=14
HOME_LAB_HOST_UID=$(id -u)
HOME_LAB_HOST_GID=$(id -g)
GMAIL_QUERY={from:no_reply@zetace.com.ar from:oficinavirtual@epe.santafe.gov.ar from:facturadigital@aguassantafesinas.com from:factura@digital.litoralgas.com.ar from:avisos@info.naranjax.com} newer_than:45d
DOCUMENT_MAX_BYTES=20971520
SIAT_TGI_ACCOUNT=
SIAT_TGI_MANAGEMENT_CODE=
MERCADOPAGO_ACCESS_TOKEN=
EOF
    echo "Created $prod_env"
else
    echo "Keeping existing $prod_env"
fi
chmod 600 "$prod_env"

docker build --file "${repo_root}/Dockerfile.dashboard" --tag "$image" "$repo_root"
HOME_LAB_SKIP_PULL=1 "${repo_root}/scripts/deploy-production.sh" "$image"

install -m 0644 "${repo_root}/infra/systemd/home-lab-production.service" \
    "${config_dir}/home-lab-production.service"
install -m 0644 "${repo_root}/infra/systemd/home-lab-backup.service" \
    "${config_dir}/home-lab-backup.service"
install -m 0644 "${repo_root}/infra/systemd/home-lab-backup.timer" \
    "${config_dir}/home-lab-backup.timer"
install -m 0755 "${repo_root}/scripts/verify-production-backup.sh" \
    "${config_dir}/verify-production-backup.sh"
install -m 0644 "${repo_root}/infra/systemd/home-lab-backup-verify.service" \
    "${config_dir}/home-lab-backup-verify.service"
install -m 0644 "${repo_root}/infra/systemd/home-lab-backup-verify.timer" \
    "${config_dir}/home-lab-backup-verify.timer"

mkdir -p "${config_home}/systemd/user"
ln -sfn "${config_dir}/home-lab-production.service" \
    "${config_home}/systemd/user/home-lab-production.service"
ln -sfn "${config_dir}/home-lab-backup.service" \
    "${config_home}/systemd/user/home-lab-backup.service"
ln -sfn "${config_dir}/home-lab-backup.timer" \
    "${config_home}/systemd/user/home-lab-backup.timer"
ln -sfn "${config_dir}/home-lab-backup-verify.service" \
    "${config_home}/systemd/user/home-lab-backup-verify.service"
ln -sfn "${config_dir}/home-lab-backup-verify.timer" \
    "${config_home}/systemd/user/home-lab-backup-verify.timer"

systemctl --user daemon-reload
systemctl --user enable --now \
    home-lab-production.service \
    home-lab-backup.timer \
    home-lab-backup-verify.timer

if ! loginctl enable-linger "$USER" 2>/dev/null; then
    echo "Could not enable user lingering automatically." >&2
    echo "Run: sudo loginctl enable-linger $USER" >&2
fi

echo "Production service installed. Check it with:"
echo "  systemctl --user status home-lab-production.service"
