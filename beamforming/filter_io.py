from __future__ import annotations

from pathlib import Path

import numpy as np


def save_filter_npz(
    path: str | Path,
    weights: np.ndarray,
    *,
    sample_rate: int,
) -> None:
    spatial_filter = np.asarray(weights, dtype=np.complex128)
    if spatial_filter.ndim not in (2, 3):
        raise ValueError("weights must have shape (channels, frequencies[, candidates])")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    np.savez(
        Path(path),
        weights=spatial_filter,
        sample_rate=np.asarray(sample_rate, dtype=np.int64),
    )


def load_filter_npz(path: str | Path) -> tuple[np.ndarray, int]:
    with np.load(Path(path), allow_pickle=False) as payload:
        if "weights" not in payload or "sample_rate" not in payload:
            raise ValueError("filter archive must contain weights and sample_rate")
        weights = np.asarray(payload["weights"], dtype=np.complex128)
        sample_rate = int(np.asarray(payload["sample_rate"]).item())
    if weights.ndim not in (2, 3):
        raise ValueError("weights must have shape (channels, frequencies[, candidates])")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return weights, sample_rate
