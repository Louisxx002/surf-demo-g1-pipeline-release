#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def build_arecord_command(
    *,
    device: str,
    channels: int,
    sample_rate: int,
    duration_sec: int,
    output: Path,
) -> list[str]:
    if channels <= 0 or sample_rate <= 0 or duration_sec <= 0:
        raise ValueError("channels, sample_rate and duration_sec must be positive")
    return [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        str(channels),
        "-d",
        str(duration_sec),
        "-t",
        "wav",
        str(output),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture unmodified multichannel ALSA audio for channel mapping."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", required=True, help="ALSA device, for example hw:2,0")
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--duration", type=int, default=10)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = build_arecord_command(
        device=args.device,
        channels=args.channels,
        sample_rate=args.sample_rate,
        duration_sec=args.duration,
        output=args.output,
    )
    print(
        f"Capturing raw {args.channels}-channel PCM16: "
        f"device={args.device} rate={args.sample_rate} output={args.output}"
    )
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
