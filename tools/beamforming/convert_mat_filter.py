#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scipy.io import loadmat


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from beamforming.filter_io import save_filter_npz  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a MATLAB fixed-beamformer filter to a NumPy runtime archive."
    )
    parser.add_argument("input_mat", type=Path)
    parser.add_argument("output_npz", type=Path)
    parser.add_argument("--variable", default="DCF_Targ_Filter")
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()

    payload = loadmat(args.input_mat)
    if args.variable not in payload:
        available = sorted(key for key in payload if not key.startswith("__"))
        raise SystemExit(
            f"variable {args.variable!r} not found; available variables: {available}"
        )
    weights = payload[args.variable]
    args.output_npz.parent.mkdir(parents=True, exist_ok=True)
    save_filter_npz(args.output_npz, weights, sample_rate=args.sample_rate)
    print(
        json.dumps(
            {
                "output": str(args.output_npz),
                "weight_shape": list(weights.shape),
                "sample_rate_hz": args.sample_rate,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
