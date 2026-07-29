#!/usr/bin/env bash
set -Eeuo pipefail

for command_name in gh curl tar sha256sum systemctl; do
    if ! command -v "$command_name" >/dev/null; then
        echo "Missing required command: $command_name" >&2
        exit 1
    fi
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository="$(cd "$repo_root" && gh repo view --json nameWithOwner --jq .nameWithOwner)"
runner_home="${XDG_DATA_HOME:-${HOME}/.local/share}/github-actions-runner/home-lab"
service_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
service_file="${service_dir}/github-actions-runner-home-lab.service"
runner_name="${HOSTNAME:-$(hostname)}-home-lab-prod"

mkdir -p "$runner_home" "$service_dir"

if [[ ! -f "${runner_home}/.runner" ]]; then
    metadata="$(mktemp)"
    archive="$(mktemp --suffix=.tar.gz)"
    cleanup() {
        rm -f "$metadata" "$archive"
    }
    trap cleanup EXIT

    gh api "repos/${repository}/actions/runners/downloads" > "$metadata"
    if [[ "$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$metadata")" == "0" ]]; then
        gh api "repos/actions/runner/releases/latest" > "$metadata"
    fi

    asset_metadata="$(python3 - "$metadata" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
if isinstance(data, list):
    for item in data:
        if item["os"] == "linux" and item["architecture"] == "x64":
            print(item["download_url"], item["sha256_checksum"], sep="\t")
            break
    else:
        raise SystemExit("GitHub did not offer a Linux x64 runner")
else:
    for item in data["assets"]:
        if item["name"].startswith("actions-runner-linux-x64-"):
            digest = item.get("digest", "")
            if not digest.startswith("sha256:"):
                raise SystemExit("GitHub runner release has no SHA-256 digest")
            print(item["browser_download_url"], digest.removeprefix("sha256:"), sep="\t")
            break
    else:
        raise SystemExit("Latest actions/runner release has no Linux x64 asset")
PY
)"
    IFS=$'\t' read -r download_url expected_checksum <<< "$asset_metadata"

    curl --fail --location --silent --show-error "$download_url" --output "$archive"
    printf '%s  %s\n' "$expected_checksum" "$archive" | sha256sum --check --status
    tar --extract --gzip --file "$archive" --directory "$runner_home"

    registration_token="$(
        gh api --method POST \
            "repos/${repository}/actions/runners/registration-token" \
            --jq .token
    )"
    (
        cd "$runner_home"
        ./config.sh \
            --url "https://github.com/${repository}" \
            --token "$registration_token" \
            --name "$runner_name" \
            --labels home-lab-prod \
            --work _work \
            --unattended \
            --replace
    )
    unset registration_token
    trap - EXIT
    cleanup
else
    echo "Keeping existing runner registration in $runner_home"
fi

cat > "$service_file" <<EOF
[Unit]
Description=GitHub Actions runner for home-lab production
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${runner_home}
ExecStart=${runner_home}/run.sh
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=90

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now github-actions-runner-home-lab.service
systemctl --user --no-pager status github-actions-runner-home-lab.service
