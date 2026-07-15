from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import loadmat, wavfile

from .fixed_mini_beamformer import float_to_matlab_pcm16, process_matlab_compatible


def verify_teacher_reference(
    reference_dir: str | Path,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    reference = Path(reference_dir)
    sample_rate, mixture = wavfile.read(reference / "mixture.wav")
    output_rate, expected = wavfile.read(reference / "out0.wav")
    weights = loadmat(reference / "DCF_Targ7.mat")["DCF_Targ_Filter"]

    if sample_rate != output_rate:
        raise ValueError(
            f"reference sample-rate mismatch: mixture={sample_rate}, output={output_rate}"
        )
    if mixture.ndim != 2:
        raise ValueError("mixture.wav must be multichannel")
    if expected.ndim != 1:
        raise ValueError("out0.wav must be mono")

    output = process_matlab_compatible(
        mixture.astype(np.float64) / 32768.0,
        weights,
        sample_rate=sample_rate,
    )
    actual = float_to_matlab_pcm16(output)
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(destination, sample_rate, actual)

    difference = actual.astype(np.int32) - expected.astype(np.int32)
    max_abs_error = int(np.max(np.abs(difference)))
    rmse = float(np.sqrt(np.mean(difference.astype(np.float64) ** 2)))
    exact_ratio = float(np.mean(difference == 0))
    return {
        "sample_rate_hz": int(sample_rate),
        "input_channels": int(mixture.shape[1]),
        "input_samples": int(mixture.shape[0]),
        "output_samples": int(actual.shape[0]),
        "weight_shape": list(weights.shape),
        "max_abs_error_lsb": max_abs_error,
        "rmse_lsb": rmse,
        "exact_sample_ratio": exact_ratio,
        "different_samples": int(np.count_nonzero(difference)),
        "accepted": (
            max_abs_error <= 1
            and rmse < 0.01
            and exact_ratio > 0.99999
        ),
    }

