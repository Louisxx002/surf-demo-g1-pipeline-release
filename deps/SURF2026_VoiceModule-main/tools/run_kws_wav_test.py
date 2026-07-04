from __future__ import annotations

import argparse
import json
from pathlib import Path
import wave

import numpy as np
import sherpa_onnx


CHUNK_SAMPLES = 3200


def find_model_file(model_dir: Path, prefix: str) -> str:
    candidates = sorted(model_dir.glob(f"{prefix}-*.int8.onnx"))
    if not candidates:
        candidates = [
            path
            for path in sorted(model_dir.glob(f"{prefix}-*.onnx"))
            if ".int8." not in path.name
        ]
    if not candidates:
        raise FileNotFoundError(f"No {prefix} model file found in {model_dir}")
    return str(candidates[-1])


def read_wav_16k_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if channels != 1 or sample_rate != 16000 or sample_width != 2:
        raise ValueError(
            f"{path} must be 16kHz mono int16 wav; "
            f"got channels={channels} sample_rate={sample_rate} sample_width={sample_width}"
        )
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def build_spotter(model_dir: Path, keywords_file: Path) -> sherpa_onnx.KeywordSpotter:
    return sherpa_onnx.KeywordSpotter(
        tokens=str(model_dir / "tokens.txt"),
        encoder=find_model_file(model_dir, "encoder"),
        decoder=find_model_file(model_dir, "decoder"),
        joiner=find_model_file(model_dir, "joiner"),
        keywords_file=str(keywords_file),
        num_trailing_blanks=2,
        provider="cpu",
    )


def detect_file(kws: sherpa_onnx.KeywordSpotter, wav_path: Path) -> dict[str, object]:
    stream = kws.create_stream()
    waveform = read_wav_16k_mono(wav_path)
    detected = ""
    for start in range(0, len(waveform), CHUNK_SAMPLES):
        chunk = waveform[start : start + CHUNK_SAMPLES]
        stream.accept_waveform(sample_rate=16000, waveform=chunk)
        while kws.is_ready(stream):
            kws.decode_stream(stream)
        result = kws.get_result(stream)
        if result:
            detected = result
            break
    return {
        "file": str(wav_path),
        "detected": bool(detected),
        "keyword": detected,
        "duration_sec": round(float(len(waveform)) / 16000.0, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sherpa-onnx KWS on wav files.")
    parser.add_argument("wav", nargs="+", type=Path)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "models" / "kws",
    )
    parser.add_argument("--keywords-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    keywords_file = args.keywords_file or (args.model_dir / "keywords.txt")
    kws = build_spotter(args.model_dir, keywords_file)
    any_missing = False
    for wav_path in args.wav:
        result = detect_file(kws, wav_path)
        if not result["detected"]:
            any_missing = True
        print(json.dumps(result, ensure_ascii=False))
    return 1 if any_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
