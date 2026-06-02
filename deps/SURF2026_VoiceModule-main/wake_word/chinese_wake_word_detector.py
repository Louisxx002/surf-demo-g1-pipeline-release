from __future__ import annotations

import logging
import pathlib
import queue
import threading
from typing import Callable

import numpy as np
import sherpa_onnx

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

CHUNK_SAMPLES = 3200   # 200ms @ 16kHz
CHUNK_BYTES   = CHUNK_SAMPLES * 2  # 16-bit PCM


def _find_model_file(model_dir: pathlib.Path, prefix: str) -> str:
    """Return an ONNX model path matching prefix, preferring int8 over full precision."""
    candidates = sorted(model_dir.glob(f"{prefix}-*.int8.onnx"))
    if not candidates:
        # exclude .int8.onnx so we only get full-precision files in the fallback
        candidates = [p for p in sorted(model_dir.glob(f"{prefix}-*.onnx"))
                      if ".int8." not in p.name]
    if not candidates:
        raise FileNotFoundError(f"No {prefix} model file found in {model_dir}")
    return str(candidates[-1])


class ChineseWakeWordDetector:
    """sherpa-onnx KeywordSpotter 中文唤醒词检测，接口与 WakeWordDetector 一致。

    push_audio() 在 AudioBus 回调线程调用；后台推理线程消费 queue。
    检测到唤醒词后 reset stream，防止连续触发。
    唤醒词通过 models/kws/keywords.txt（音素格式）配置，无需重新训练。
    """

    def __init__(
        self,
        on_detected: Callable[[str], None],
        model_dir: str = CONFIG.kws_model_dir,
    ) -> None:
        self._on_detected = on_detected

        model = pathlib.Path(model_dir)
        self._kws = sherpa_onnx.KeywordSpotter(
            tokens=str(model / "tokens.txt"),
            encoder=_find_model_file(model, "encoder"),
            decoder=_find_model_file(model, "decoder"),
            joiner=_find_model_file(model, "joiner"),
            keywords_file=str(model / "keywords.txt"),
            num_trailing_blanks=2,
            provider="cpu",
        )
        self._stream = self._kws.create_stream()

        self._buffer = b""
        self._buffer_lock = threading.Lock()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="zh-wakeword-infer"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def push_audio(self, pcm: bytes) -> None:
        with self._buffer_lock:
            self._buffer += pcm
            while len(self._buffer) >= CHUNK_BYTES:
                chunk = self._buffer[:CHUNK_BYTES]
                self._buffer = self._buffer[CHUNK_BYTES:]
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:
                    pass

    def _run(self) -> None:
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._infer(chunk)

    def _infer(self, chunk: bytes) -> None:
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        self._stream.accept_waveform(sample_rate=CONFIG.sample_rate, waveform=samples)
        while self._kws.is_ready(self._stream):
            self._kws.decode_stream(self._stream)
        result = self._kws.get_result(self._stream)

        if result:
            self._kws.reset_stream(self._stream)
            try:
                self._on_detected(result)
            except Exception:
                logger.exception("on_detected callback raised")
