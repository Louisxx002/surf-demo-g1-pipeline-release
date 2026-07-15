#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scipy.io import wavfile


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from beamforming.channel_diagnostics import analyze_channels  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report per-channel levels, clipping, silence, duplication and correlation."
    )
    parser.add_argument("wav", type=Path)
    args = parser.parse_args()

    sample_rate, samples = wavfile.read(args.wav)
    report = analyze_channels(samples, sample_rate=sample_rate)
    report["file"] = str(args.wav)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
