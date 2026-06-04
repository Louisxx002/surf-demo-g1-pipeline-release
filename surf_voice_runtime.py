from __future__ import annotations

import json
import logging
import os
import socket
import time

import numpy as np

from asr.asr_engine import ASREngine
from audio.audio_bus import AudioBus
from audio.mic_capture import MicCapture
from config.voice_config import CONFIG
from vad.vad_engine import VADEngine
from voice_id.speaker_database import SpeakerDatabase
from voice_id.voiceprint_recognizer import VoiceprintRecognizer
from wake_word.chinese_wake_word_detector import ChineseWakeWordDetector
from wake_word.wake_word_detector import WakeWordDetector
from wake_word.wakeup_dispatcher import WakeupDispatcher

from pipeline_log.pipeline_logger import PipelineLogger, SessionLog


logging.basicConfig(level=logging.INFO, format="[surf_voice_runtime] %(message)s")
logger = logging.getLogger(__name__)


class UdpEventSink:
    def __init__(self) -> None:
        self._addr = (
            os.environ.get("SURF_BRIDGE_HOST", "127.0.0.1"),
            int(os.environ.get("SURF_BRIDGE_PORT", "18765")),
        )
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def publish(self, topic: str, msg_type: str, data) -> None:
        payload = {
            "topic": topic,
            "type": msg_type,
            "data": data,
            "time": time.time(),
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._sock.sendto(raw, self._addr)


class SurfVoiceRuntime:
    def __init__(self) -> None:
        self._sink = UdpEventSink()
        self._pipeline_logger = PipelineLogger()
        self._session_log: SessionLog | None = None
        self._session_id = ""
        self._recording = False
        self._asr_audio_frames: list[bytes] = []
        self._asr_t0 = 0.0
        self._bus = AudioBus()
        self._vad = VADEngine()
        self._dispatch = WakeupDispatcher()
        self._dispatch.register(self._on_wake)
        if CONFIG.wake_word_lang == "zh":
            self._wakeword = ChineseWakeWordDetector(on_detected=self._dispatch.on_detection)
        else:
            self._wakeword = WakeWordDetector(on_detected=self._dispatch.on_detection)
        self._asr = ASREngine(on_result=self._on_asr)
        self._vprint = VoiceprintRecognizer(on_embedding=self._on_embedding)
        self._speaker_db = SpeakerDatabase()
        self._current_speaker = ""
        self._audio_source = CONFIG.audio_source

        if CONFIG.audio_source == "robot":
            from audio.robot_mic_capture import RobotMicCapture

            self._mic = RobotMicCapture(bus=self._bus)
        else:
            self._mic = MicCapture(bus=self._bus)

        self._bus.register(self._vad.process_frame)
        self._bus.register(self._wakeword.push_audio)
        self._bus.register(self._asr.push_audio)
        self._bus.register(self._vprint.push_audio)
        self._bus.register(self._collect_audio)
        self._vad.register(self._on_vad)

        self._asr_deadline = 0.0
        self._vad_holdoff_until = 0.0

    def start(self) -> None:
        self._wakeword.start()
        try:
            self._mic.start()
        except OSError as exc:
            if self._audio_source == "robot":
                raise RuntimeError(
                    "robot mic failed to start; keep robot mic only and fix Unitree audio/DDS connectivity"
                ) from exc
            raise
        logger.info("ready, listening via %s", self._audio_source)

    def stop(self) -> None:
        self._mic.stop()
        self._wakeword.stop()

    def spin(self) -> None:
        while True:
            if self._asr_deadline and time.monotonic() > self._asr_deadline:
                logger.info("asr deadline reached; forcing transcription")
                self._asr_deadline = 0.0
                self._recording = False
                self._save_audio()
                self._asr.stop_and_transcribe()
            time.sleep(0.1)

    def _on_wake(self, word: str) -> None:
        self._session_id = self._new_session(word)
        logger.info("wake: %s session=%s", word, self._session_id)
        self._sink.publish(
            "/wake_word_event",
            "string",
            json.dumps(
                {"word": word, "session_id": self._session_id, "time": time.time()},
                ensure_ascii=False,
            ),
        )
        bus_snapshot = self._bus.get_buffer()
        self._recording = True
        self._asr_audio_frames = list(bus_snapshot[-15:])
        self._asr.start_recording(initial_audio=b"".join(bus_snapshot[-15:]))
        self._vprint.start_capture(initial_audio=b"".join(bus_snapshot))
        self._asr_t0 = time.monotonic()
        self._asr_deadline = time.monotonic() + CONFIG.asr_window_sec
        self._vad_holdoff_until = time.monotonic() + CONFIG.vad_holdoff_sec
        if self._session_log:
            self._session_log.record("asr_started", asr_window_sec=CONFIG.asr_window_sec)

    def _on_vad(self, is_speech: bool) -> None:
        logger.info("vad: %s", is_speech)
        self._sink.publish("/vad_state", "bool", is_speech)
        if is_speech and self._recording:
            self._cancel_asr_deadline("vad_speech")
        if not is_speech and self._recording and time.monotonic() > self._vad_holdoff_until:
            self._recording = False
            self._asr_deadline = 0.0
            self._save_audio()
            self._asr.stop_and_transcribe()

    def _on_asr(self, text: str) -> None:
        logger.info("asr: %s speaker=%s session=%s", text, self._current_speaker, self._session_id)
        self._sink.publish(
            "/audio_msg",
            "string",
            json.dumps(
                {
                    "text": text,
                    "speaker": self._current_speaker,
                    "session_id": self._session_id or "default",
                    "time": time.time(),
                },
                ensure_ascii=False,
            ),
        )
        if self._session_log:
            self._session_log.record_duration(
                "asr_result",
                start=self._asr_t0,
                text=text,
                speaker=self._current_speaker,
                session_id=self._session_id or "default",
            )

    def _on_embedding(self, embedding: np.ndarray) -> None:
        self._current_speaker, score = self._speaker_db.identify_with_score(embedding)
        if self._recording:
            self._cancel_asr_deadline("speaker_embedding")
        logger.info("speaker: %s score=%.3f", self._current_speaker, score)
        self._sink.publish(
            "/speaker_id",
            "string",
            json.dumps({"speaker": self._current_speaker, "score": score}, ensure_ascii=False),
        )
        if self._session_log:
            self._session_log.record(
                "speaker_id",
                label=self._current_speaker,
                score=score,
                session_id=self._session_id or "default",
            )

    def _collect_audio(self, pcm: bytes) -> None:
        if self._recording:
            self._asr_audio_frames.append(pcm)

    def _cancel_asr_deadline(self, reason: str) -> None:
        if not self._asr_deadline:
            return
        if os.environ.get("VOICE_KEEP_ASR_DEADLINE", "").strip().lower() in ("1", "true", "yes", "on"):
            logger.info("asr deadline kept despite: %s", reason)
            if self._session_log:
                self._session_log.record(
                    "asr_deadline_kept",
                    reason=reason,
                    session_id=self._session_id or "default",
                )
            return
        self._asr_deadline = 0.0
        logger.info("asr deadline cancelled: %s", reason)
        if self._session_log:
            self._session_log.record("asr_deadline_cancelled", reason=reason, session_id=self._session_id or "default")

    def _new_session(self, wake_word: str) -> str:
        session = self._pipeline_logger.start_session(wake_word)
        self._session_log = session
        self._session_id = session.session_id
        return self._session_id

    def _save_audio(self) -> None:
        if self._session_log and self._asr_audio_frames:
            self._session_log.save_audio(self._asr_audio_frames)


def main() -> None:
    runtime = SurfVoiceRuntime()
    runtime.start()
    try:
        runtime.spin()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
