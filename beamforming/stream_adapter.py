from __future__ import annotations

import numpy as np

from .fixed_mini_beamformer import FixedMiniBeamformerStream, float_to_matlab_pcm16


DEFAULT_EFFECTIVE_CHANNEL_INDICES = (0, 1, 2, 3)


class FixedBeamformerPacketizer:
    """Convert interleaved multichannel PCM16 into mono fixed-size packets."""

    def __init__(
        self,
        weights: np.ndarray,
        *,
        source_channels: int,
        channel_indices: tuple[int, ...] | None = None,
        sample_rate: int = 16000,
        output_packet_ms: int = 20,
    ) -> None:
        spatial_filter = np.asarray(weights, dtype=np.complex128)
        weight_channels = spatial_filter.shape[0] if spatial_filter.ndim >= 1 else 0
        if channel_indices is None:
            channel_indices = tuple(range(weight_channels))
        if source_channels <= 0:
            raise ValueError("source_channels must be positive")
        if len(channel_indices) != weight_channels:
            raise ValueError(
                f"channel_indices must select {weight_channels} channels, got {len(channel_indices)}"
            )
        if len(set(channel_indices)) != len(channel_indices):
            raise ValueError("channel_indices must not contain duplicates")
        if any(index < 0 or index >= source_channels for index in channel_indices):
            raise ValueError("channel_indices are outside the source channel range")
        if output_packet_ms <= 0:
            raise ValueError("output_packet_ms must be positive")

        self.source_channels = source_channels
        self.channel_indices = np.asarray(channel_indices, dtype=np.int64)
        self.output_packet_samples = sample_rate * output_packet_ms // 1000
        if self.output_packet_samples <= 0:
            raise ValueError("output packet duration is too short for the sample rate")
        self._beamformer = FixedMiniBeamformerStream(
            spatial_filter,
            sample_rate=sample_rate,
            matlab_compatible_tail=False,
        )
        self._pending_output = np.empty(0, dtype=np.int16)

    @property
    def pending_output_samples(self) -> int:
        return int(self._pending_output.shape[0])

    def push_pcm16(self, payload: bytes) -> list[bytes]:
        frame_bytes = self.source_channels * np.dtype(np.int16).itemsize
        if len(payload) % frame_bytes != 0:
            raise ValueError(
                f"PCM16 payload length must be divisible by {frame_bytes} bytes"
            )
        if not payload:
            return []

        source = np.frombuffer(payload, dtype="<i2").reshape(-1, self.source_channels)
        selected = source[:, self.channel_indices].astype(np.float64) / 32768.0
        enhanced = self._beamformer.push(selected)
        if enhanced.size:
            self._pending_output = np.concatenate(
                (self._pending_output, float_to_matlab_pcm16(enhanced))
            )

        packets = []
        while self._pending_output.shape[0] >= self.output_packet_samples:
            packet = self._pending_output[: self.output_packet_samples]
            self._pending_output = self._pending_output[self.output_packet_samples :]
            packets.append(packet.astype("<i2", copy=False).tobytes())
        return packets
