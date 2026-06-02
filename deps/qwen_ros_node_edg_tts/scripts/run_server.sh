#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a
export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"

"${QWEN_PYTHON}" -m uvicorn qwen_server:app --host "${QWEN_SERVER_HOST}" --port "${QWEN_SERVER_PORT}"
