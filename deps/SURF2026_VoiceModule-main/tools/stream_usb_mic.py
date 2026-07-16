"""Stream an 8-channel USB microphone to the computer as mono PCM16 UDP.

The default ``mean4`` mode averages only source channels 0, 1, 2, and 3.
The optional ``beamformer`` mode applies the supplied fixed spatial filter.
Both modes preserve the existing downstream wire contract: 16 kHz, mono,
PCM16, 20 ms (640-byte) UDP packets.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path


def _add_runtime_root() -> Path:
    script_path = Path(__file__).resolve()
    for parent in script_path.parents:
        if (parent / "beamforming").is_dir():
            sys.path.insert(0, str(parent))
            return parent
    raise RuntimeError(
        "beamforming runtime package not found; run scripts/deploy_robot_mic_runtime.sh"
    )


RUNTIME_ROOT = _add_runtime_root()

from beamforming.mic_runtime import (  # noqa: E402
    build_arecord_stream_command,
    build_mic_packetizer,
    parse_channel_indices,
)


DEFAULT_DESTINATION = "192.168.123.225"
DEFAULT_PORT = 5556
DEFAULT_DEVICE = "hw:2,0"
DEFAULT_CHANNELS = 8
DEFAULT_CHANNEL_MAP = "0,1,2,3"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_INPUT_FRAME_MS = 16
DEFAULT_OUTPUT_PACKET_MS = 20
DEFAULT_FILTER = RUNTIME_ROOT / "filters" / "DCF_Targ7_runtime.npz"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="8-channel USB microphone processor and UDP streamer",
    )
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="ALSA device")
    parser.add_argument("--dest", default=DEFAULT_DESTINATION, help="computer IP")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--mode", choices=("mean4", "beamformer"), default="mean4")
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    parser.add_argument("--channel-map", default=DEFAULT_CHANNEL_MAP)
    parser.add_argument("--filter", type=Path, default=DEFAULT_FILTER)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--input-frame-ms", type=int, default=DEFAULT_INPUT_FRAME_MS)
    parser.add_argument("--packet-ms", type=int, default=DEFAULT_OUTPUT_PACKET_MS)
    return parser


def _probe_capture(command: list[str]) -> None:
    probe_command = command[:-2] + ["-d", "1", "-q", "/dev/null"]
    result = subprocess.run(probe_command, capture_output=True)
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(
            f"ALSA device cannot capture the requested channel layout: {error}"
        )


def main() -> None:
    args = build_parser().parse_args()
    if args.input_frame_ms <= 0:
        raise SystemExit("--input-frame-ms must be positive")

    channel_indices = parse_channel_indices(args.channel_map)
    filter_path = args.filter if args.mode == "beamformer" else None
    packetizer = build_mic_packetizer(
        mode=args.mode,
        source_channels=args.channels,
        channel_indices=channel_indices,
        filter_path=filter_path,
        sample_rate=args.sample_rate,
        output_packet_ms=args.packet_ms,
    )
    capture_command = build_arecord_stream_command(
        device=args.device,
        channels=args.channels,
        sample_rate=args.sample_rate,
    )
    _probe_capture(capture_command)

    input_samples = args.sample_rate * args.input_frame_ms // 1000
    input_frame_bytes = input_samples * args.channels * 2
    if input_samples <= 0:
        raise SystemExit("input frame duration is too short")

    destination = (args.dest, args.port)
    print(
        f"USB mic device={args.device} source={args.channels}ch "
        f"mode={args.mode} selected={','.join(map(str, channel_indices))}",
        flush=True,
    )
    if args.mode == "beamformer":
        print(f"beamformer filter={args.filter}", flush=True)
    print(
        f"processing={args.input_frame_ms}ms input -> {args.packet_ms}ms mono UDP "
        f"destination={args.dest}:{args.port}",
        flush=True,
    )
    print("streaming started; Ctrl+C to stop", flush=True)

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    process: subprocess.Popen[bytes] | None = None
    packet_count = 0
    input_frame_count = 0
    started_at = time.monotonic()
    try:
        process = subprocess.Popen(
            capture_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pending = b""
        while True:
            assert process.stdout is not None
            chunk = process.stdout.read(input_frame_bytes)
            if not chunk:
                error = (
                    process.stderr.read().decode(errors="replace").strip()
                    if process.stderr
                    else ""
                )
                raise RuntimeError(f"arecord stopped unexpectedly: {error}")
            pending += chunk
            while len(pending) >= input_frame_bytes:
                frame = pending[:input_frame_bytes]
                pending = pending[input_frame_bytes:]
                input_frame_count += 1
                for packet in packetizer.push_pcm16(frame):
                    udp_socket.sendto(packet, destination)
                    packet_count += 1
    except KeyboardInterrupt:
        print("\nstreaming stopped by user", flush=True)
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        udp_socket.close()
        elapsed = max(time.monotonic() - started_at, 0.001)
        print(
            f"summary input_frames={input_frame_count} udp_packets={packet_count} "
            f"elapsed_sec={elapsed:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
