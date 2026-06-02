#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

mkdir -p "${QWEN_RUNTIME_DIR}"
cd "${WORKSPACE_ROOT}/xjtlu-rag-system"

exec "${QWEN_PYTHON}" -m uvicorn app:app --host "${RAG_SERVER_HOST}" --port "${RAG_SERVER_PORT}"
