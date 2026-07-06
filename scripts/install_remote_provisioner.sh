#!/usr/bin/env bash
set -euo pipefail

SOURCE_PATH="${1:-scripts/tiny_provisioner_remote.py}"
TARGET_PATH="${2:-/usr/local/bin/tiny-provisioner-remote}"
NETWORK_NAME="${TINY_PROVISIONER_NETWORK:-tiny-provisioner-apps}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

if [[ ! -f "${SOURCE_PATH}" ]]; then
  echo "Source script not found: ${SOURCE_PATH}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not on PATH." >&2
  exit 1
fi

install -m 0755 "${SOURCE_PATH}" "${TARGET_PATH}"

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  docker network create \
    --driver bridge \
    --label tiny-provisioner.managed=true \
    "${NETWORK_NAME}" >/dev/null
fi

"${TARGET_PATH}" logs --external-id "ssh:localhost:missing-demo" >/dev/null

echo "Installed ${TARGET_PATH}"
echo "Verified remote command wrapper and Docker network ${NETWORK_NAME}"
