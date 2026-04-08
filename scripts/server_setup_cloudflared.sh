#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root."
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_SOURCE="${1:-${REPO_ROOT}/cloudflare/dead-market-tunnel.linux.yml}"
CONFIG_DIR="/root/.cloudflared"
CONFIG_TARGET="${CONFIG_DIR}/config.yml"
TUNNEL_ID="2e986217-27c7-443c-8b25-e5fcbdde9a86"
CREDENTIALS_FILE="${CONFIG_DIR}/${TUNNEL_ID}.json"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed. Run scripts/server_install_cloudflared_ubuntu.sh first."
  exit 1
fi

if [[ ! -f "${CONFIG_SOURCE}" ]]; then
  echo "Cloudflare config template not found: ${CONFIG_SOURCE}"
  exit 1
fi

mkdir -p "${CONFIG_DIR}"

if [[ ! -f "${CREDENTIALS_FILE}" ]]; then
  echo "Credentials file is missing: ${CREDENTIALS_FILE}"
  echo "Copy it from your Windows machine first:"
  echo "  C:\\Users\\Tigran\\.cloudflared\\${TUNNEL_ID}.json"
  exit 1
fi

cp "${CONFIG_SOURCE}" "${CONFIG_TARGET}"

echo "Validating ingress config..."
cloudflared tunnel ingress validate --config "${CONFIG_TARGET}"

echo "Installing cloudflared as a systemd service..."
cloudflared --config "${CONFIG_TARGET}" service install

systemctl enable cloudflared
systemctl restart cloudflared

echo ""
systemctl --no-pager --full status cloudflared || true

echo ""
echo "Recent logs:"
journalctl -u cloudflared -n 30 --no-pager || true
