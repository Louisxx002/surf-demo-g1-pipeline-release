"""
stream_usb_mic.py — 在机器人上运行，把 USB 麦克风音频通过 UDP 单播发到电脑。

用法（在机器人 SSH 终端里）：
    python3 tools/stream_usb_mic.py

电脑端用 VOICE_ROBOT_MIC_PORT=5556 接收：
    VOICE_AUDIO_SOURCE=robot VOICE_ROBOT_MIC_PORT=5556 python run_robot.py

查看 USB 麦设备号：
    arecord -l

如果 USB 麦不是 hw:1,0，用 --device 参数指定：
    python3 tools/stream_usb_mic.py --device hw:2,0
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys

DEST_IP   = "192.168.123.225"   # 电脑 IP（eth1 在机器人网段的地址）
PORT      = 5556                # 避免和原生麦的 5555 冲突
DEVICE    = "hw:1,0"            # USB 麦默认 ALSA 设备，arecord -l 可查
RATE      = 16000
FRAME_MS  = 20
FRAME_BYTES = int(RATE * FRAME_MS / 1000) * 2  # 640 bytes = 320 samples × 16bit


def main() -> None:
    parser = argparse.ArgumentParser(description="USB 麦克风 UDP 流发送器")
    parser.add_argument("--device",  default=DEVICE,   help="ALSA 设备（默认 hw:1,0）")
    parser.add_argument("--dest",    default=DEST_IP,  help="目标 IP（电脑 IP）")
    parser.add_argument("--port",    default=PORT, type=int, help="目标端口（默认 5556）")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (args.dest, args.port)

    # 先尝试单声道，不行自动切双声道混成单声道
    for ch in (1, 2, 4, 8):
        test = subprocess.run(
            ["arecord", "-D", args.device, "-f", "S16_LE", "-r", str(RATE), "-c", str(ch), "-d", "1", "-q", "/dev/null"],
            capture_output=True,
        )
        if test.returncode == 0:
            channels = ch
            break
    else:
        print("[错误] 设备不支持 1/2/4/8 声道，请检查设备", file=sys.stderr)
        sys.exit(1)

    cmd = [
        "arecord",
        "-D", args.device,
        "-f", "S16_LE",
        "-r", str(RATE),
        "-c", str(channels),
        "-q",
        "-",
    ]

    # 双声道时每帧字节数翻倍，读进来再混成单声道
    read_bytes = FRAME_BYTES * channels

    print(f"USB 麦设备: {args.device}  声道: {channels}ch → 单声道输出")
    print(f"发送到: {args.dest}:{args.port}")
    print(f"帧大小: {FRAME_BYTES} bytes ({FRAME_MS}ms)")
    print("开始推流... Ctrl+C 停止\n")

    proc: subprocess.Popen[bytes] | None = None
    try:
        import numpy as np
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pending = b""
        while True:
            assert proc.stdout is not None
            chunk = proc.stdout.read(read_bytes * 4)
            if not chunk:
                err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
                print(f"[错误] arecord 退出: {err}", file=sys.stderr)
                break
            pending += chunk
            while len(pending) >= read_bytes:
                frame_raw = pending[:read_bytes]
                pending = pending[read_bytes:]
                if channels > 1:
                    samples = np.frombuffer(frame_raw, dtype=np.int16).reshape(-1, channels)
                    frame_raw = samples.mean(axis=1).astype(np.int16).tobytes()
                sock.sendto(frame_raw, dest)
    except KeyboardInterrupt:
        print("\n停止。")
    finally:
        if proc is not None:
            proc.terminate()
        sock.close()


if __name__ == "__main__":
    main()
