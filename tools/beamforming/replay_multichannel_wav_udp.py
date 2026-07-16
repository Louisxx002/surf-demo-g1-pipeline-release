from __future__ import annotations

import argparse
import socket
import sys
import time
import wave
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from beamforming.mic_runtime import build_mic_packetizer, parse_channel_indices


def iter_wav_packets(
    path: str | Path,
    packetizer: object,
    *,
    input_frame_ms: int = 16,
) -> Iterator[bytes]:
    if input_frame_ms <= 0:
        raise ValueError("input_frame_ms must be positive")
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getsampwidth() != 2:
            raise ValueError("input WAV must use PCM16 samples")
        frame_samples = wav_file.getframerate() * input_frame_ms // 1000
        if frame_samples <= 0:
            raise ValueError("input frame duration is too short")
        while True:
            payload = wav_file.readframes(frame_samples)
            if not payload:
                break
            frame_bytes = wav_file.getnchannels() * 2
            complete_bytes = len(payload) - (len(payload) % frame_bytes)
            if complete_bytes == 0:
                break
            for packet in packetizer.push_pcm16(payload[:complete_bytes]):
                yield packet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay an 8-channel WAV through mean4 or fixed beamforming to UDP",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--mode", choices=("mean4", "beamformer"), default="mean4")
    parser.add_argument("--filter", type=Path)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--channel-map", default="0,1,2,3")
    parser.add_argument("--dest", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5556)
    parser.add_argument("--input-frame-ms", type=int, default=16)
    parser.add_argument("--packet-ms", type=int, default=20)
    parser.add_argument(
        "--no-realtime",
        action="store_true",
        help="Send packets without sleeping between 20 ms output packets",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with wave.open(str(args.input), "rb") as wav_file:
        source_channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
    if source_channels != args.channels:
        raise SystemExit(
            f"input WAV has {source_channels} channels, expected {args.channels}"
        )

    packetizer = build_mic_packetizer(
        mode=args.mode,
        source_channels=source_channels,
        channel_indices=parse_channel_indices(args.channel_map),
        filter_path=args.filter,
        sample_rate=sample_rate,
        output_packet_ms=args.packet_ms,
    )
    destination = (args.dest, args.port)
    packet_count = 0
    started_at = time.perf_counter()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        for packet in iter_wav_packets(
            args.input,
            packetizer,
            input_frame_ms=args.input_frame_ms,
        ):
            udp_socket.sendto(packet, destination)
            packet_count += 1
            if not args.no_realtime:
                target = started_at + packet_count * args.packet_ms / 1000.0
                time.sleep(max(0.0, target - time.perf_counter()))

    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    print(
        f"replay complete mode={args.mode} packets={packet_count} "
        f"packet_bytes={args.packet_ms * sample_rate // 1000 * 2} "
        f"destination={args.dest}:{args.port} elapsed_ms={elapsed_ms:.1f}"
    )


if __name__ == "__main__":
    main()
