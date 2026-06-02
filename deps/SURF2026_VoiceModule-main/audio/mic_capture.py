from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

from audio.audio_bus import AudioBus
from config.voice_config import CONFIG

logger = logging.getLogger(__name__)


class MicCapture:
    """sounddevice 麦克风采集，把音频切成标准帧持续推入 AudioBus。

    sounddevice callback 每次给的样本数不保证整除 frame_bytes，
    用 _pending 缓冲拼凑完整帧再推送。
    """

    def __init__(
        self,
        bus: AudioBus,
        device: int | None = CONFIG.mic_device,
        sample_rate: int = CONFIG.sample_rate,
    ) -> None:
        self._bus = bus
        self._device = device
        self._sample_rate = sample_rate
        self._input_rate = sample_rate
        self._pending = b""
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        last_exc: Exception | None = None
        for rate in (self._sample_rate, 48000, 44100, 32000, 22050):
            try:
                self._stream = sd.InputStream(
                    device=self._device,
                    channels=1,
                    samplerate=rate,
                    dtype="float32",
                    callback=self._callback,
                )
                self._stream.start()
                self._input_rate = rate
                logger.info("MicCapture started at %d Hz", rate)
                return
            except Exception as exc:
                last_exc = exc
                if self._stream is not None:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
        raise last_exc or RuntimeError("Failed to start microphone capture")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        if status:
            logger.warning("sounddevice status: %s", status)
        samples = indata[:, 0].astype(np.float32)
        if self._input_rate != self._sample_rate and len(samples) > 1:
            in_x = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
            out_len = max(1, int(round(len(samples) * self._sample_rate / self._input_rate)))
            out_x = np.linspace(0.0, 1.0, num=out_len, endpoint=False)
            samples = np.interp(out_x, in_x, samples).astype(np.float32)
        pcm = (samples * 32768).clip(-32768, 32767).astype(np.int16).tobytes()
        self._pending += pcm
        while len(self._pending) >= CONFIG.frame_bytes:
            frame, self._pending = (
                self._pending[:CONFIG.frame_bytes],
                self._pending[CONFIG.frame_bytes:],
            )
            self._bus.push(frame)
