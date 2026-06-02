#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

set -a
source "${PROJECT_ROOT}/config/default.env"
set +a

export QWEN_RUNTIME_DIR="${PROJECT_ROOT}/runtime"
export PYTHONDONTWRITEBYTECODE=1
export ROS_LOG_DIR="${PROJECT_ROOT}/runtime/ros_logs"
export PYTHONPATH="${PROJECT_ROOT}/third_party/unitree_sdk2_python:${PYTHONPATH:-}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
mkdir -p "${QWEN_RUNTIME_DIR}" "${ROS_LOG_DIR}"

echo "[1/9] Checking required project files"
test -f project_config.py
test -f qwen_ros_node_edg_tts.py
test -f qwen_server.py
test -f unitree_audio_player.py
test -f asr_dds_to_ros_bridge.py
test -f wav.py
test -f config/default.env
test -f requirements.txt
test -f scripts/run_asr_bridge.sh
test -f scripts/run_full_pipeline.sh
test -f scripts/stop_full_pipeline.sh
test -d third_party/unitree_sdk2_python/unitree_sdk2py
test -d "${QWEN_MODEL_PATH}"

echo "[2/9] Checking no Python runtime caches are packaged"
if find . -type d -name __pycache__ | grep -q .; then
  echo "Found __pycache__ directories:"
  find . -type d -name __pycache__
  exit 1
fi
if find . -type f \( -name '*.pyc' -o -name '*.pyo' \) | grep -q .; then
  echo "Found Python bytecode files:"
  find . -type f \( -name '*.pyc' -o -name '*.pyo' \)
  exit 1
fi

echo "[3/9] Checking Python syntax"
"${QWEN_PYTHON}" - <<'PY'
import ast
from pathlib import Path

for name in ("project_config.py", "qwen_ros_node_edg_tts.py", "qwen_server.py", "unitree_audio_player.py", "wav.py"):
    path = Path(name)
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"syntax ok: {path}")
PY

echo "[4/9] Checking Python package imports"
"${QWEN_PYTHON}" - <<'PY'
from pathlib import Path
from project_config import CONFIG
import requests
import fastapi
import edge_tts
import torch
import transformers

print("runtime_dir:", CONFIG.runtime_dir)
print("model_path:", CONFIG.model_path)
assert CONFIG.runtime_dir.exists()
assert Path(CONFIG.model_path).exists()
print("core imports ok")
PY

echo "[5/9] Checking wake-word logic"
set +u
source /opt/ros/jazzy/setup.bash
set -u
"${QWEN_PYTHON}" - <<'PY'
from qwen_ros_node_edg_tts import QwenAudioNode

cases = {
    "小g 你叫什么名字": "你叫什么名字",
    "西浦小g现在几点了": "现在几点了",
    "小 G 明天天气怎么样": "明天天气怎么样",
    "今天天气不错": None,
    "小g": "",
}
for text, expected in cases.items():
    got = QwenAudioNode.strip_wake_word(text)
    print(text, "=>", got)
    assert got == expected, (text, got, expected)
print("wake-word logic ok")
PY

echo "[6/9] Checking ffmpeg mp3->wav conversion"
"${QWEN_PYTHON}" - <<'PY'
from pathlib import Path
from project_config import CONFIG
import wave

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
wav_path = CONFIG.runtime_dir / "check_input.wav"
with wave.open(str(wav_path), "wb") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(16000)
    f.writeframes(b"\x00\x00" * 1600)
print(wav_path)
PY
ffmpeg -y -hide_banner -loglevel error \
  -i "${QWEN_RUNTIME_DIR}/check_input.wav" \
  "${QWEN_RUNTIME_DIR}/check_input.mp3"
ffmpeg -y -hide_banner -loglevel error \
  -i "${QWEN_RUNTIME_DIR}/check_input.mp3" \
  -ar 16000 -ac 1 "${QWEN_RUNTIME_DIR}/check_output.wav"
test -s "${QWEN_RUNTIME_DIR}/check_output.wav"
echo "ffmpeg conversion ok"

echo "[7/9] Checking ROS2 std_msgs/String transport"
"${QWEN_PYTHON}" - <<'PY'
import os
import subprocess
import sys
import time

topic = "/qwen/check_audio_msg"
python = sys.executable
env = os.environ.copy()
env["PYTHONDONTWRITEBYTECODE"] = "1"

subscriber_code = f"""
import rclpy
from std_msgs.msg import String
received = {{}}
rclpy.init(args=None)
node = rclpy.create_node('qwen_check_subscriber')
def cb(msg):
    received['data'] = msg.data
node.create_subscription(String, {topic!r}, cb, 10)
deadline = node.get_clock().now().nanoseconds / 1e9 + 6.0
while 'data' not in received:
    rclpy.spin_once(node, timeout_sec=0.1)
    if node.get_clock().now().nanoseconds / 1e9 > deadline:
        raise TimeoutError('timed out waiting for String')
print('ROS_SUBSCRIBER_OK', received['data'], flush=True)
node.destroy_node()
rclpy.shutdown()
"""

publisher_code = f"""
import time
import rclpy
from std_msgs.msg import String
rclpy.init(args=None)
node = rclpy.create_node('qwen_check_publisher')
pub = node.create_publisher(String, {topic!r}, 10)
time.sleep(1.0)
msg = String()
msg.data = '{{\"text\":\"小g 你好\"}}'
for _ in range(5):
    pub.publish(msg)
    rclpy.spin_once(node, timeout_sec=0.05)
    time.sleep(0.1)
print('ROS_PUBLISHER_OK', flush=True)
node.destroy_node()
rclpy.shutdown()
"""

sub = subprocess.Popen([python, "-c", subscriber_code], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.0)
pub = subprocess.run([python, "-c", publisher_code], env=env, text=True, capture_output=True, timeout=10)
out, _ = sub.communicate(timeout=10)
print(pub.stdout, end="")
if pub.stderr:
    print(pub.stderr, end="", file=sys.stderr)
print(out, end="")
if pub.returncode != 0:
    raise SystemExit(pub.returncode)
if sub.returncode != 0:
    raise SystemExit(sub.returncode)
assert 'ROS_SUBSCRIBER_OK {"text":"小g 你好"}' in out
print("ros2 string transport ok")
PY

echo "[8/9] Checking Unitree DDS Python imports from project third_party"
"${QWEN_PYTHON}" - <<'PY'
from pathlib import Path
import inspect
import unitree_sdk2py
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

root = Path.cwd().resolve()
source = Path(inspect.getfile(unitree_sdk2py)).resolve()
print("unitree_sdk2py:", source)
assert root in source.parents, source
print("unitree dds imports ok")
PY

echo "[9/9] Checking optional Qwen server health if running"
"${QWEN_PYTHON}" - <<'PY'
import requests
from project_config import CONFIG

health_url = CONFIG.qwen_server_url.rsplit("/", 1)[0] + "/health"
session = requests.Session()
session.trust_env = False
try:
    response = session.get(health_url, timeout=2.0)
except Exception as exc:
    print(f"Qwen server not running or unreachable, skipped health check: {exc}")
else:
    response.raise_for_status()
    print("qwen server health ok:", response.json())
PY

echo "QWEN ROS DDS FULL CHECK PASSED"
