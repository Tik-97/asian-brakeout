#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root."
  exit 1
fi

mkdir -p /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

. /etc/os-release
CODENAME="${VERSION_CODENAME:-}"

if [[ -z "${CODENAME}" ]]; then
  echo "Could not detect Ubuntu codename from /etc/os-release"
  exit 1
fi

echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared ${CODENAME} main" \
  | tee /etc/apt/sources.list.d/cloudflared.list >/dev/null

apt-get update
apt-get install -y cloudflared

cloudflared --version
