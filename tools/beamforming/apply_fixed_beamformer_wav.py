#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from beamforming.filter_io import load_filter_npz  # noqa: E402
from beamforming.fixed_mini_beamformer import (  # noqa: E402
    float_to_matlab_pcm16,
    process_matlab_compatible,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a fixed beamformer to a PCM16 WAV.")
    parser.add_argument("input_wav", type=Path)
    parser.add_argument("filter_npz", type=Path)
    parser.add_argument("output_wav", type=Path)
    args = parser.parse_args()

    sample_rate, samples = wavfile.read(args.input_wav)
    if samples.dtype != np.int16 or samples.ndim != 2:
        raise SystemExit("input WAV must be multichannel PCM16")
    weights, filter_sample_rate = load_filter_npz(args.filter_npz)
    if sample_rate != filter_sample_rate:
        raise SystemExit(
            f"sample-rate mismatch: WAV={sample_rate}, filter={filter_sample_rate}"
        )
    if samples.shape[1] != weights.shape[0]:
        raise SystemExit(
            f"channel mismatch: WAV={samples.shape[1]}, filter={weights.shape[0]}"
        )

    enhanced = process_matlab_compatible(
        samples.astype(np.float64) / 32768.0,
        weights,
        sample_rate=sample_rate,
    )
    output_pcm = float_to_matlab_pcm16(enhanced)
    args.output_wav.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(args.output_wav, sample_rate, output_pcm)
    print(
        json.dumps(
            {
                "input": str(args.input_wav),
                "output": str(args.output_wav),
                "sample_rate_hz": sample_rate,
                "input_channels": samples.shape[1],
                "output_channels": 1,
                "samples": output_pcm.shape[0],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
