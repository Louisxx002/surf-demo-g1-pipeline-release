#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

mkdir -p "${OLLAMA_MODELS}"
export OLLAMA_HOST="${OLLAMA_BASE_URL#http://}"
export OLLAMA_MODELS

exec "${OLLAMA_BIN}" serve
