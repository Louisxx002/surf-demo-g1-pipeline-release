from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np
import torch
from pyannote.audio import Inference, Model

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)


class VoiceprintRecognizer:
    """唤醒词触发后录制固定时长音频，提取说话人声纹 embedding。

    流程：
      1. 唤醒词触发时调用 start_capture()
      2. push_audio() 持续积累 PCM，满 capture_sec 秒后停止录制
      3. 后台线程提取 256 维 embedding，通过 on_embedding 回调输出

    使用固定时长（默认 3.5 秒）而不是完整录音，原因：
    - 完整录音时长不可控，会导致提取延迟波动
    - 3.5 秒 = ~1s 唤醒词回填 + ~2.5s 指令，足够模型稳定提取特征
    - 避免录入多人混音影响准确率
    """

    def __init__(
        self,
        on_embedding: Callable[[np.ndarray], None],
        model_name: str = CONFIG.voiceprint_model,
        capture_sec: float = CONFIG.voiceprint_capture_sec,
        sample_rate: int = CONFIG.sample_rate,
    ) -> None:
        self._on_embedding = on_embedding
        self._capture_sec = capture_sec
        self._sample_rate = sample_rate
        self._target_bytes = int(sample_rate * capture_sec) * 2  # 16-bit PCM

        model = Model.from_pretrained(model_name)
        self._inference = Inference(model, window="whole")

        self._buffer = b""
        self._capturing = False
        self._lock = threading.Lock()

    def start_capture(self, initial_audio: bytes = b"") -> None:
        with self._lock:
            self._buffer = initial_audio
            self._capturing = True

    def push_audio(self, pcm: bytes) -> None:
        with self._lock:
            if not self._capturing:
                return
            self._buffer += pcm
            if len(self._buffer) < self._target_bytes:
                return
            audio_data = self._buffer[:self._target_bytes]
            self._capturing = False

        threading.Thread(target=self._extract, args=(audio_data,), daemon=True).start()

    def _extract(self, audio_data: bytes) -> None:
        samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        waveform = torch.from_numpy(samples).unsqueeze(0)  # (1, N)
        embedding = self._inference({"waveform": waveform, "sample_rate": self._sample_rate})
        try:
            self._on_embedding(np.array(embedding))
        except Exception:
            logger.exception("on_embedding callback raised")
