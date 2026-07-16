from __future__ import annotations

from pathlib import Path

from .filter_io import load_filter_npz
from .stream_adapter import (
    DEFAULT_EFFECTIVE_CHANNEL_INDICES,
    FixedBeamformerPacketizer,
    MeanChannelPacketizer,
)


SUPPORTED_MODES = ("mean4", "beamformer")


def parse_channel_indices(value: str) -> tuple[int, ...]:
    try:
        indices = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError(f"invalid channel map: {value!r}") from exc
    if not indices:
        raise ValueError("channel map must not be empty")
    if len(set(indices)) != len(indices):
        raise ValueError("channel map must not contain duplicates")
    if any(index < 0 for index in indices):
        raise ValueError("channel map must contain non-negative indices")
    return indices


def build_arecord_stream_command(
    *,
    device: str,
    channels: int,
    sample_rate: int,
) -> list[str]:
    if channels <= 0:
        raise ValueError("channels must be positive")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
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
        "-q",
        "-",
    ]


def build_mic_packetizer(
    *,
    mode: str,
    source_channels: int,
    channel_indices: tuple[int, ...] = DEFAULT_EFFECTIVE_CHANNEL_INDICES,
    filter_path: str | Path | None = None,
    sample_rate: int = 16000,
    output_packet_ms: int = 20,
) -> MeanChannelPacketizer | FixedBeamformerPacketizer:
    normalized_mode = mode.strip().lower()
    if normalized_mode == "mean4":
        return MeanChannelPacketizer(
            source_channels=source_channels,
            channel_indices=channel_indices,
            sample_rate=sample_rate,
            output_packet_ms=output_packet_ms,
        )
    if normalized_mode == "beamformer":
        if filter_path is None:
            raise ValueError("beamformer mode requires filter_path")
        weights, filter_sample_rate = load_filter_npz(filter_path)
        if filter_sample_rate != sample_rate:
            raise ValueError(
                f"filter sample rate is {filter_sample_rate}, expected {sample_rate}"
            )
        return FixedBeamformerPacketizer(
            weights,
            source_channels=source_channels,
            channel_indices=channel_indices,
            sample_rate=sample_rate,
            output_packet_ms=output_packet_ms,
        )
    raise ValueError(
        f"unsupported microphone processing mode {mode!r}; "
        f"expected one of {', '.join(SUPPORTED_MODES)}"
    )
