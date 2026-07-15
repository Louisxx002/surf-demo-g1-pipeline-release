from __future__ import annotations

import numpy as np


def _normalized_samples(samples: np.ndarray) -> np.ndarray:
    values = np.asarray(samples)
    if values.ndim != 2:
        raise ValueError("samples must have shape (sample_count, channel_count)")
    if np.issubdtype(values.dtype, np.integer):
        scale = float(max(abs(np.iinfo(values.dtype).min), np.iinfo(values.dtype).max + 1))
        return values.astype(np.float64) / scale
    return values.astype(np.float64)


def analyze_channels(
    samples: np.ndarray,
    *,
    sample_rate: int,
    silence_dbfs: float = -70.0,
    duplicate_correlation: float = 0.9999,
    clipping_threshold: float = 0.999,
) -> dict[str, object]:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    signal = _normalized_samples(samples)
    if signal.shape[0] == 0 or signal.shape[1] == 0:
        raise ValueError("samples must not be empty")

    rms = np.sqrt(np.mean(signal**2, axis=0))
    rms_dbfs = 20.0 * np.log10(np.maximum(rms, np.finfo(np.float64).tiny))
    peak = np.max(np.abs(signal), axis=0)
    dc = np.mean(signal, axis=0)
    clipping_ratio = np.mean(np.abs(signal) >= clipping_threshold, axis=0)
    silent = rms_dbfs <= silence_dbfs

    correlation = np.eye(signal.shape[1], dtype=np.float64)
    active_indices = np.flatnonzero(~silent)
    if active_indices.size > 1:
        active_correlation = np.corrcoef(signal[:, active_indices], rowvar=False)
        correlation[np.ix_(active_indices, active_indices)] = np.nan_to_num(
            active_correlation,
            nan=0.0,
        )

    duplicate_pairs: list[list[int]] = []
    for left in range(signal.shape[1]):
        for right in range(left + 1, signal.shape[1]):
            if not silent[left] and not silent[right] and correlation[left, right] >= duplicate_correlation:
                duplicate_pairs.append([left + 1, right + 1])

    channels = []
    for index in range(signal.shape[1]):
        channels.append(
            {
                "channel": index + 1,
                "rms_dbfs": round(float(rms_dbfs[index]), 3),
                "peak": round(float(peak[index]), 6),
                "dc": round(float(dc[index]), 6),
                "clipping_ratio": round(float(clipping_ratio[index]), 6),
                "silent": bool(silent[index]),
            }
        )

    return {
        "sample_rate_hz": sample_rate,
        "sample_count": signal.shape[0],
        "duration_sec": signal.shape[0] / sample_rate,
        "channel_count": signal.shape[1],
        "channels": channels,
        "silent_channels": [int(index + 1) for index in np.flatnonzero(silent)],
        "clipped_channels": [
            int(index + 1) for index in np.flatnonzero(clipping_ratio > 0.0)
        ],
        "duplicate_pairs": duplicate_pairs,
        "correlation": np.round(correlation, 6).tolist(),
    }
