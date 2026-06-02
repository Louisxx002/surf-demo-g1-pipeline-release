#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: env_set.sh KEY VALUE" >&2
  exit 1
fi

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${WORKSPACE_ROOT}/config/local.env"
KEY="$1"
VALUE="$2"
ESCAPED_VALUE="${VALUE//\\/\\\\}"
ESCAPED_VALUE="${ESCAPED_VALUE//\"/\\\"}"

touch "${CONFIG_FILE}"

if grep -q "^${KEY}=" "${CONFIG_FILE}"; then
  sed -i "s|^${KEY}=.*|${KEY}=\"${ESCAPED_VALUE}\"|" "${CONFIG_FILE}"
else
  printf '\n%s="%s"\n' "${KEY}" "${ESCAPED_VALUE}" >> "${CONFIG_FILE}"
fi
