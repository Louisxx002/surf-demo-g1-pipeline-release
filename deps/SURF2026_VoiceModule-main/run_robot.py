"""
run_robot.py — 机器人音频流启动器。

用法（conda voice312 环境，WSL2）：
    python run_robot.py                      # 机器人原生麦（5555 端口）
    VOICE_ROBOT_MIC_PORT=5556 python run_robot.py  # 外置 USB 麦（stream_usb_mic.py 发的流）

机器人侧需要同时运行（SSH 进去执行）：
    python3 tools/stream_usb_mic.py          # 原生麦 → 保持不变（不用启动）
    python3 tools/stream_usb_mic.py --port 5556  # USB 麦 → 需要启动此脚本
"""
import os
from pathlib import Path
import runpy

os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")
os.environ["VOICE_AUDIO_SOURCE"] = "robot"

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

runpy.run_path(str(ROOT / "standalone_test.py"), run_name="__main__")
