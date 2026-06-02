from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

import numpy as np
import openwakeword.model

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

CHUNK_SAMPLES = 1280   # 80ms @ 16kHz, openWakeWord 期望输入大小
CHUNK_BYTES = CHUNK_SAMPLES * 2  # 16-bit PCM


class WakeWordDetector:
    """openWakeWord 封装，作为 AudioBus 消费者。

    push_audio() 在 AudioBus 回调线程中调用；后台线程负责推理，
    触发 on_detected 回调。
    """

    def __init__(
        self,
        on_detected: Callable[[str], None],
        threshold: float = CONFIG.wake_threshold,
        model_paths: list[str] | None = None,
        inference_framework: str = "onnx",
    ) -> None:
        self._on_detected = on_detected
        self._threshold = threshold

        kwargs: dict = {"inference_framework": inference_framework}
        if model_paths:
            kwargs["wakeword_models"] = model_paths
        self._model = openwakeword.model.Model(**kwargs)

        self._buffer = b""
        self._buffer_lock = threading.Lock()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=10)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="wakeword-infer")
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
                chunk, self._buffer = self._buffer[:CHUNK_BYTES], self._buffer[CHUNK_BYTES:]
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:
                    pass  # 推理跟不上时丢弃最旧的 chunk

    def _run(self) -> None:
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            audio = np.frombuffer(chunk, dtype=np.int16)
            for word, score in self._model.predict(audio).items():
                if score >= self._threshold:
                    try:
                        self._on_detected(word)
                    except Exception:
                        logger.exception("on_detected callback raised")
