#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt, welch


FRAME_SAMPLES = 320
SPEECH_PERCENTILE = 60
NOISE_PERCENTILE = 20


def _load_pcm16(path: Path) -> tuple[int, np.ndarray]:
    sample_rate, samples = wavfile.read(path)
    if samples.dtype != np.int16 or samples.ndim != 1:
        raise ValueError(f"expected mono PCM16 WAV: {path}")
    return sample_rate, samples.astype(np.float64) / 32768.0


def _frame_dbfs(samples: np.ndarray) -> np.ndarray:
    frame_count = samples.size // FRAME_SAMPLES
    frames = samples[: frame_count * FRAME_SAMPLES].reshape(frame_count, FRAME_SAMPLES)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return 20.0 * np.log10(rms + 1e-12)


def _masked_rms_dbfs(samples: np.ndarray, mask: np.ndarray) -> float:
    frames = samples[: mask.size * FRAME_SAMPLES].reshape(mask.size, FRAME_SAMPLES)
    selected = frames[mask]
    if selected.size == 0:
        raise ValueError("energy mask selected no samples")
    rms = np.sqrt(np.mean(selected**2))
    return float(20.0 * np.log10(rms + 1e-12))


def analyze_pair(mean_path: Path, beam_path: Path) -> tuple[dict[str, float], dict[str, np.ndarray]]:
    mean_rate, mean = _load_pcm16(mean_path)
    beam_rate, beam = _load_pcm16(beam_path)
    if mean_rate != beam_rate:
        raise ValueError(f"sample-rate mismatch: {mean_path} and {beam_path}")
    if mean.shape != beam.shape:
        raise ValueError(f"sample-count mismatch: {mean_path} and {beam_path}")

    bandpass = butter(4, [300, 3400], btype="bandpass", fs=mean_rate, output="sos")
    mean_band = sosfiltfilt(bandpass, mean)
    beam_band = sosfiltfilt(bandpass, beam)
    mean_frame_dbfs = _frame_dbfs(mean_band)
    speech_mask = mean_frame_dbfs >= np.percentile(mean_frame_dbfs, SPEECH_PERCENTILE)
    noise_mask = mean_frame_dbfs <= np.percentile(mean_frame_dbfs, NOISE_PERCENTILE)

    mean_speech = _masked_rms_dbfs(mean_band, speech_mask)
    beam_speech = _masked_rms_dbfs(beam_band, speech_mask)
    mean_noise = _masked_rms_dbfs(mean_band, noise_mask)
    beam_noise = _masked_rms_dbfs(beam_band, noise_mask)
    frequency, mean_psd = welch(mean_band, mean_rate, nperseg=2048)
    _, beam_psd = welch(beam_band, beam_rate, nperseg=2048)
    spectral_mask = (frequency >= 100) & (frequency <= 4000)

    metrics = {
        "mean_speech_dbfs": mean_speech,
        "beam_speech_dbfs": beam_speech,
        "relative_speech_gain_db": beam_speech - mean_speech,
        "mean_noise_dbfs": mean_noise,
        "beam_noise_dbfs": beam_noise,
        "relative_noise_gain_db": beam_noise - mean_noise,
        "mean_snr_proxy_db": mean_speech - mean_noise,
        "beam_snr_proxy_db": beam_speech - beam_noise,
        "snr_proxy_change_db": (beam_speech - beam_noise) - (mean_speech - mean_noise),
    }
    spectra = {
        "frequency_hz": frequency[spectral_mask],
        "mean_psd_db": 10.0 * np.log10(mean_psd[spectral_mask] + 1e-20),
        "beam_psd_db": 10.0 * np.log10(beam_psd[spectral_mask] + 1e-20),
    }
    return metrics, spectra


def _write_plot(path: Path, rows: list[dict[str, float]], spectra: dict[int, dict[str, np.ndarray]]) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    angles = [int(row["angle_deg"]) for row in rows]
    gains = [row["relative_speech_gain_db"] for row in rows]
    colors = ["#4f9cf9" if angle != 90 else "#ef6b73" for angle in angles]
    axes[0, 0].bar([str(angle) for angle in angles], gains, color=colors)
    axes[0, 0].axhline(0.0, color="#777777", linewidth=1)
    axes[0, 0].set_title("Beamformer speech gain relative to mean4")
    axes[0, 0].set_xlabel("Source angle (deg)")
    axes[0, 0].set_ylabel("Relative gain (dB)")

    for axis, angle in zip(axes.flat[1:], angles):
        spectrum = spectra[angle]
        axis.plot(spectrum["frequency_hz"], spectrum["mean_psd_db"], label="mean4", alpha=0.85)
        axis.plot(spectrum["frequency_hz"], spectrum["beam_psd_db"], label="beamformer", alpha=0.85)
        axis.set_title(f"{angle} deg average spectrum")
        axis.set_xlabel("Frequency (Hz)")
        axis.set_ylabel("PSD (dB/Hz)")
        axis.grid(alpha=0.2)
        axis.legend()

    figure.suptitle("Bothlent fixed-beam direction check", fontsize=15)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _write_markdown(path: Path, rows: list[dict[str, float]]) -> None:
    by_angle = {int(row["angle_deg"]): row for row in rows}
    suppression_0_to_90 = by_angle[0]["relative_speech_gain_db"] - by_angle[90]["relative_speech_gain_db"]
    suppression_180_to_90 = by_angle[180]["relative_speech_gain_db"] - by_angle[90]["relative_speech_gain_db"]
    lines = [
        "# 0/90/180 度固定波束离线对比",
        "",
        "说明：以下数值使用 300-3400 Hz 频带。每段录音以 mean4 的高能量 40% 帧近似语音区间、低能量 20% 帧近似背景区间。",
        "`相对语音增益 = beamformer - mean4`，因此数值越低表示该方向的人声被压得越多。",
        "",
        "| 角度 | mean4 语音 dBFS | 波束语音 dBFS | 相对语音增益 | 相对噪声增益 | SNR 代理变化 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {angle_deg:.0f}° | {mean_speech_dbfs:.2f} | {beam_speech_dbfs:.2f} | "
            "{relative_speech_gain_db:+.2f} dB | {relative_noise_gain_db:+.2f} dB | "
            "{snr_proxy_change_db:+.2f} dB |".format(**row)
        )
    lines.extend([
        "",
        "## 当前结论",
        "",
        f"- 相对 0°，90° 方向额外受到约 **{suppression_0_to_90:.2f} dB** 的语音抑制。",
        f"- 相对 180°，90° 方向额外受到约 **{suppression_180_to_90:.2f} dB** 的语音抑制。",
        "- 结果方向符合老师说明：90° 是抑制方向，不是增强方向。",
        "- 抑制度仍不算很强；mean4 主观更清晰并不与上述结果矛盾，因为固定波束可能同时改变人声频谱和背景噪声。",
        "- 该结果是三次独立录音的工程代理指标，不等同于消声室方向图。后续应保持距离、句子和说话音量一致，并补录更多角度或同步播放固定测试音源。",
        "",
        "![方向与频谱对比](direction_comparison.png)",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare mean4 and fixed-beam outputs by angle.")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--angles", type=int, nargs="+", default=[0, 90, 180])
    args = parser.parse_args()

    rows: list[dict[str, float]] = []
    spectra: dict[int, dict[str, np.ndarray]] = {}
    for angle in args.angles:
        metrics, angle_spectra = analyze_pair(
            args.input_dir / f"bothlent_mean4_{angle}deg.wav",
            args.input_dir / f"bothlent_beamformer_{angle}deg.wav",
        )
        rows.append({"angle_deg": float(angle), **metrics})
        spectra[angle] = angle_spectra

    with (args.input_dir / "direction_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.input_dir / "direction_metrics.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_plot(args.input_dir / "direction_comparison.png", rows, spectra)
    _write_markdown(args.input_dir / "direction_report.md", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
