"""
record_usb_mic.py — 用本地 USB 麦克风录制原始音频，保存到 recordings/。

用法：
    python tools/record_usb_mic.py

操作：
    按 Enter 开始录音
    按 Ctrl+C 停止当前段，自动保存并询问是否继续

文件命名：usb_YYYYMMDD_HHMMSS_<备注>.wav
"""
from __future__ import annotations

import os
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd

os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")

SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2
FRAME_MS     = 20
BLOCKSIZE    = int(SAMPLE_RATE * FRAME_MS / 1000)

OUT_DIR = Path(__file__).resolve().parent.parent / "recordings"


def record_one(label: str) -> list[bytes]:
    frames: list[bytes] = []
    stop_event = threading.Event()

    def callback(indata: np.ndarray, frame_count: int, time_info, status) -> None:
        pcm = (indata[:, 0] * 32768).clip(-32768, 32767).astype(np.int16).tobytes()
        frames.append(pcm)

    stream = sd.InputStream(
        channels=CHANNELS,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        blocksize=BLOCKSIZE,
        callback=callback,
    )

    original_sigint = __import__("signal").getsignal(__import__("signal").SIGINT)

    def on_stop(*_):
        stop_event.set()

    __import__("signal").signal(__import__("signal").SIGINT, on_stop)
    stream.start()

    try:
        while not stop_event.is_set():
            secs = len(frames) * FRAME_MS / 1000
            print(f"  ● 录制中 [{label}]  {secs:.1f}s  (Ctrl+C 停止)", end="\r")
            time.sleep(0.2)
    finally:
        stream.stop()
        stream.close()
        __import__("signal").signal(__import__("signal").SIGINT, original_sigint)

    print()
    return frames


def save_wav(frames: list[bytes], path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        for frame in frames:
            wf.writeframes(frame)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 50)
    print("  USB 麦克风录音")
    print(f"  输出目录: {OUT_DIR}")
    print("=" * 50)
    print("按 Enter 开始，Ctrl+C 停止当前段\n")

    clip = 1
    while True:
        try:
            note = input(f"[第 {clip} 段] 输入备注（直接回车跳过）: ").strip()
        except KeyboardInterrupt:
            print("\n退出。")
            break

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{note}" if note else ""
        out_path = OUT_DIR / f"usb_{ts}{suffix}.wav"

        try:
            frames = record_one(note or f"clip{clip}")
        except KeyboardInterrupt:
            frames = []

        if not frames:
            print("  [跳过] 未录到音频\n")
            continue

        save_wav(frames, out_path)
        secs = len(frames) * FRAME_MS / 1000
        print(f"  ✓ 已保存 {secs:.1f}s → {out_path.name}\n")
        clip += 1

        try:
            again = input("继续录下一段？(Enter 继续 / q 退出): ").strip().lower()
            if again == "q":
                break
        except KeyboardInterrupt:
            break

    print("全部完成。")


if __name__ == "__main__":
    main()
