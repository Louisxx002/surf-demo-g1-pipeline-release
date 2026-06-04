"""
record_robot_mic.py — 分位置/距离录制宇树 G1 麦克风阵列原始音频。

用法：
    python tools/record_robot_mic.py

脚本会依次引导录制 9 段音频：
    正前方 × (20cm / 1m / 2m)
    左侧   × (20cm / 1m / 2m)
    右侧   × (20cm / 1m / 2m)

操作：
    按 Enter 开始录音
    按 Ctrl+C 停止当前段，自动保存并进入下一段

输出目录：recordings/
文件命名：raw_20260522_143012_front_20cm.wav

前提：
    - 机器人网线已连接
    - 本机 IP 为 192.168.123.225（可用 VOICE_ROBOT_MIC_IF 覆盖）
"""
from __future__ import annotations

import os
import signal
import socket
import struct
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────

SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2
FRAME_MS     = 20
FRAME_BYTES  = int(SAMPLE_RATE * FRAME_MS / 1000) * SAMPLE_WIDTH

GROUP_IP  = os.environ.get("VOICE_ROBOT_MIC_GROUP", "239.168.123.161")
PORT      = int(os.environ.get("VOICE_ROBOT_MIC_PORT", "5555"))
LOCAL_IF  = os.environ.get("VOICE_ROBOT_MIC_IF", "192.168.123.225")

OUT_DIR = Path(__file__).resolve().parent.parent / "recordings"

SESSIONS = [
    ("front", "20cm"),
    ("front", "1m"),
    ("front", "2m"),
    ("left",  "20cm"),
    ("left",  "1m"),
    ("left",  "2m"),
    ("right", "20cm"),
    ("right", "1m"),
    ("right", "2m"),
]

POSITION_ZH = {"front": "正前方", "left": "左侧", "right": "右侧"}

# ── 录音核心 ──────────────────────────────────────────────────────────────────

def open_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(GROUP_IP), socket.inet_aton(LOCAL_IF))
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        print(f"\n[错误] 无法加入组播组 {GROUP_IP}（接口 {LOCAL_IF}）")
        print(f"  请确认机器人网线已连接，且本机 IP 为 {LOCAL_IF}")
        print(f"  原始错误：{e}")
        sys.exit(1)
    sock.settimeout(1.0)
    return sock


def record_one(sock: socket.socket, label: str) -> list[bytes]:
    """录音直到 Ctrl+C，返回 PCM 帧列表。"""
    frames: list[bytes] = []
    stop_event = threading.Event()

    def recv_loop() -> None:
        pending = b""
        while not stop_event.is_set():
            try:
                data, _ = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break
            pending += data
            while len(pending) >= FRAME_BYTES:
                frames.append(pending[:FRAME_BYTES])
                pending = pending[FRAME_BYTES:]

    original_sigint = signal.getsignal(signal.SIGINT)

    def on_stop(*_):
        stop_event.set()

    signal.signal(signal.SIGINT, on_stop)
    thread = threading.Thread(target=recv_loop, daemon=True)
    thread.start()

    try:
        while not stop_event.is_set():
            secs = len(frames) * FRAME_MS / 1000
            print(f"  ● 录制中 [{label}]  {secs:.1f}s  (Ctrl+C 停止)", end="\r")
            time.sleep(0.2)
    finally:
        stop_event.set()
        thread.join(timeout=3)
        signal.signal(signal.SIGINT, original_sigint)

    print()
    return frames


def save_wav(frames: list[bytes], path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        for frame in frames:
            wf.writeframes(frame)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 55)
    print("  宇树 G1 麦克风阵列原始录音")
    print(f"  组播: {GROUP_IP}:{PORT}  接口: {LOCAL_IF}")
    print(f"  输出: {OUT_DIR}")
    print("=" * 55)
    print(f"  共 {len(SESSIONS)} 段录音，每段按 Enter 开始，Ctrl+C 停止")
    print()

    sock = open_socket()

    try:
        for i, (position, distance) in enumerate(SESSIONS, 1):
            pos_zh = POSITION_ZH[position]
            label  = f"{position}_{distance}"
            ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = OUT_DIR / f"raw_{ts}_{label}.wav"

            print(f"[{i}/{len(SESSIONS)}] {pos_zh}  距离: {distance}")
            print(f"  → 请站到指定位置后按 Enter 开始录音...")
            try:
                input()
            except KeyboardInterrupt:
                print("\n已跳过剩余录音，退出。")
                break

            frames = record_one(sock, f"{pos_zh} {distance}")

            if not frames:
                print("  [警告] 未收到音频，跳过保存")
                continue

            save_wav(frames, out_path)
            secs = len(frames) * FRAME_MS / 1000
            print(f"  ✓ 已保存 {secs:.1f}s → {out_path.name}")
            print()

    finally:
        sock.close()

    print("全部录音完成。")


if __name__ == "__main__":
    main()
