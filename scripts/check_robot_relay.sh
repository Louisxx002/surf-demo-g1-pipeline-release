#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${WORKSPACE_ROOT}"

set -a
source "${WORKSPACE_ROOT}/config/default.env"
set +a

"${LLM_PYTHON}" - <<'PY'
import os
import time

from robot_relay.robot_relay_client import RobotRelayClient

host = os.environ.get("ROBOT_RELAY_HOST", "192.168.123.164")
port = int(os.environ.get("ROBOT_RELAY_PORT", "9999"))
timeout = float(os.environ.get("ROBOT_RELAY_TIMEOUT_SEC", "5"))

client = RobotRelayClient(host, port, timeout_sec=timeout)
t0 = time.time()
response = client.health()
dt = (time.time() - t0) * 1000
print(f"robot relay health ok endpoint={host}:{port} round_trip_ms={dt:.1f} response={response}")
PY

