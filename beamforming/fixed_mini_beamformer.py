from __future__ import annotations

import numpy as np


WINDOW_MS = 32
HOP_MS = 16


def _validate_inputs(
    input_signal: np.ndarray,
    weights: np.ndarray,
    sample_rate: int,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    signal = np.asarray(input_signal, dtype=np.float64)
    spatial_filter = np.asarray(weights, dtype=np.complex128)

    if signal.ndim != 2:
        raise ValueError("input_signal must have shape (samples, channels)")
    if spatial_filter.ndim == 2:
        spatial_filter = spatial_filter[:, :, np.newaxis]
    if spatial_filter.ndim != 3:
        raise ValueError("weights must have shape (channels, frequencies[, candidates])")
    if signal.shape[1] != spatial_filter.shape[0]:
        raise ValueError(
            f"channel mismatch: signal has {signal.shape[1]}, "
            f"weights require {spatial_filter.shape[0]}"
        )
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    window_length = int(np.floor(WINDOW_MS * sample_rate / 1000))
    hop_length = window_length // 2
    expected_frequencies = window_length // 2 + 1
    if spatial_filter.shape[1] != expected_frequencies:
        raise ValueError(
            f"weight frequency bins must be {expected_frequencies}, "
            f"got {spatial_filter.shape[1]}"
        )
    return signal, spatial_filter, window_length, hop_length


def process_matlab_compatible(
    input_signal: np.ndarray,
    weights: np.ndarray,
    *,
    sample_rate: int = 16000,
) -> np.ndarray:
    """Reproduce the supplied MATLAB Fixed_Mini_Beamformer output.

    The returned floating-point signal keeps the reference implementation's
    finite-file frame count and zero-filled tail behavior.
    """

    signal, spatial_filter, _, _ = _validate_inputs(
        input_signal,
        weights,
        sample_rate,
    )
    stream = FixedMiniBeamformerStream(
        spatial_filter,
        sample_rate=sample_rate,
        matlab_compatible_tail=True,
    )
    return np.concatenate((stream.push(signal), stream.flush()))


class FixedMiniBeamformerStream:
    """Stateful 32 ms / 16 ms-hop fixed beamformer.

    ``matlab_compatible_tail`` retains one hop of look-ahead so finite-file
    output exactly follows the supplied MATLAB frame-count rule. Set it to
    ``False`` for live processing, where the first hop should be emitted as
    soon as the first 32 ms analysis window is available.
    """

    def __init__(
        self,
        weights: np.ndarray,
        *,
        sample_rate: int = 16000,
        matlab_compatible_tail: bool = False,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        spatial_filter = np.asarray(weights, dtype=np.complex128)
        if spatial_filter.ndim == 2:
            spatial_filter = spatial_filter[:, :, np.newaxis]
        if spatial_filter.ndim != 3:
            raise ValueError("weights must have shape (channels, frequencies[, candidates])")

        self.sample_rate = sample_rate
        self.window_length = int(np.floor(WINDOW_MS * sample_rate / 1000))
        self.hop_length = self.window_length // 2
        self.frequency_count = self.window_length // 2 + 1
        if spatial_filter.shape[1] != self.frequency_count:
            raise ValueError(
                f"weight frequency bins must be {self.frequency_count}, "
                f"got {spatial_filter.shape[1]}"
            )

        self.weights = spatial_filter
        self.channel_count = spatial_filter.shape[0]
        self.candidate_count = spatial_filter.shape[2]
        self.matlab_compatible_tail = matlab_compatible_tail
        self.window = np.sin(
            (np.arange(self.window_length, dtype=np.float64) + 0.5)
            * np.pi
            / self.window_length
        )
        self._input = np.empty((0, self.channel_count), dtype=np.float64)
        self._overlap_tail: np.ndarray | None = None
        self._smoothed_spectrum = np.zeros(
            (self.frequency_count, self.candidate_count),
            dtype=np.float64,
        )
        self._candidate_spectrum = np.zeros(
            (self.frequency_count, self.candidate_count),
            dtype=np.complex128,
        )
        self._total_input_samples = 0
        self._output_samples = 0
        self._closed = False

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        spectrum = np.fft.fft(
            frame * self.window[:, np.newaxis],
            n=self.window_length,
            axis=0,
        )
        self._candidate_spectrum.fill(0.0)
        for candidate in range(self.candidate_count):
            self._candidate_spectrum[1:, candidate] = np.sum(
                np.conj(self.weights[:, 1:, candidate]).T
                * spectrum[1 : self.frequency_count],
                axis=1,
            )

        self._smoothed_spectrum = (
            0.15 * self._smoothed_spectrum
            + 0.85 * np.abs(self._candidate_spectrum) ** 2
        )
        candidate_power = np.sum(self._smoothed_spectrum[19:80], axis=0)
        selected = int(np.argmin(candidate_power))
        positive = self._candidate_spectrum[:, selected]
        full_spectrum = np.concatenate((positive, np.conj(positive[-2:0:-1])))
        return self.window * np.fft.ifft(full_spectrum).real

    def push(self, samples: np.ndarray) -> np.ndarray:
        if self._closed:
            raise RuntimeError("cannot push samples after flush")
        chunk = np.asarray(samples, dtype=np.float64)
        if chunk.ndim != 2 or chunk.shape[1] != self.channel_count:
            raise ValueError(
                f"samples must have shape (N, {self.channel_count}), got {chunk.shape}"
            )
        if chunk.shape[0] == 0:
            return np.empty(0, dtype=np.float64)

        self._total_input_samples += chunk.shape[0]
        self._input = np.concatenate((self._input, chunk), axis=0)
        required = self.window_length + (
            self.hop_length if self.matlab_compatible_tail else 0
        )
        output_blocks: list[np.ndarray] = []
        while self._input.shape[0] >= required:
            contribution = self._process_frame(self._input[: self.window_length])
            first_half = contribution[: self.hop_length]
            if self._overlap_tail is not None:
                first_half = self._overlap_tail + first_half
            output_blocks.append(first_half)
            self._overlap_tail = contribution[self.hop_length :]
            self._input = self._input[self.hop_length :]
            self._output_samples += self.hop_length

        if not output_blocks:
            return np.empty(0, dtype=np.float64)
        return np.concatenate(output_blocks)

    def flush(self) -> np.ndarray:
        if self._closed:
            return np.empty(0, dtype=np.float64)
        self._closed = True

        remaining = self._total_input_samples - self._output_samples
        parts: list[np.ndarray] = []
        if self._overlap_tail is not None and remaining > 0:
            tail = self._overlap_tail[:remaining]
            parts.append(tail)
            remaining -= tail.shape[0]
        if remaining > 0:
            parts.append(np.zeros(remaining, dtype=np.float64))
        if not parts:
            return np.empty(0, dtype=np.float64)
        return np.concatenate(parts)


def float_to_matlab_pcm16(signal: np.ndarray) -> np.ndarray:
    """Quantize normalized floats like MATLAB audiowrite's PCM16 path."""

    values = np.asarray(signal, dtype=np.float64)
    return np.clip(np.floor(values * 32768.0), -32768, 32767).astype(np.int16)
