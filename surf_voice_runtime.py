from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path

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
from turn_detection.runtime_shadow import TurnShadowRuntime


logging.basicConfig(level=logging.INFO, format="[surf_voice_runtime] %(message)s")
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def _wake_light_command_path() -> Path:
    value = os.environ.get("LLM_WAKE_LIGHT_COMMAND_FILE")
    if value:
        return Path(value)
    return Path(os.environ.get("LLM_RUNTIME_DIR", "runtime")) / "wake_light_command.json"


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
        self._turn_shadow: TurnShadowRuntime | None = None
        self._session_id = ""
        self._started_at = time.time()
        self._recording = False
        self._asr_audio_frames: list[bytes] = []
        self._asr_t0 = 0.0
        self._bus = AudioBus()
        self._vad = VADEngine(CONFIG.vad_aggressiveness)
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
        self._followup_enable = _env_bool("LLM_FOLLOWUP_ENABLE", True)
        self._followup_until = 0.0
        self._followup_session_id = ""
        self._followup_control_path = Path(
            os.environ.get("LLM_FOLLOWUP_CONTROL_FILE", "runtime/followup_control.json")
        )
        self._followup_control_mtime = 0.0
        self._followup_guard_until = 0.0
        self._tts_guard_enable = _env_bool("LLM_TTS_GUARD_ENABLE", True)
        self._tts_guard_path = Path(os.environ.get("LLM_TTS_GUARD_FILE", "runtime/tts_guard.json"))
        self._standby_ack_event_path = Path(
            os.environ.get("LLM_STANDBY_ACK_EVENT_FILE", "runtime/standby_ack_event.json")
        )

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
        self._mirror_turn_shadow("close")

    def spin(self) -> None:
        while True:
            self._poll_followup_control()
            if self._followup_session_id and self._followup_until and time.monotonic() > self._followup_until:
                self._close_followup_window("timeout")
            if self._asr_deadline and time.monotonic() > self._asr_deadline:
                logger.info("asr max recording deadline reached; forcing transcription")
                self._asr_deadline = 0.0
                self._recording = False
                self._save_audio()
                self._asr.stop_and_transcribe()
            time.sleep(max(0.01, CONFIG.followup_control_poll_sec))

    def _on_wake(self, word: str) -> None:
        self._close_followup_window("new_wake")
        self._session_id = self._new_session(word)
        self._mirror_turn_shadow(
            "submit_wake",
            word,
            agent_playing=self._is_tts_guard_active,
        )
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
        asr_preroll = self._asr_preroll(bus_snapshot)
        self._recording = True
        self._asr_audio_frames = asr_preroll
        self._asr.start_recording(initial_audio=b"".join(asr_preroll))
        self._vprint.start_capture(initial_audio=b"".join(bus_snapshot))
        self._asr_t0 = time.monotonic()
        self._arm_asr_max_recording_deadline()
        self._vad_holdoff_until = time.monotonic() + CONFIG.vad_holdoff_sec
        if self._session_log:
            self._session_log.record("asr_started", max_recording_sec=CONFIG.asr_max_recording_sec)

    def _on_vad(self, is_speech: bool) -> None:
        logger.info("vad: %s", is_speech)
        self._sink.publish("/vad_state", "bool", is_speech)
        self._mirror_turn_shadow(
            "submit_vad",
            is_speech,
            agent_playing=self._is_tts_guard_active,
        )
        if is_speech and not self._recording and self._followup_active():
            if self._is_tts_guard_active():
                logger.info("follow-up speech ignored due to tts guard")
                return
            self._start_followup_recording()
            return
        if not is_speech and self._recording and time.monotonic() > self._vad_holdoff_until:
            self._recording = False
            self._asr_deadline = 0.0
            self._save_audio()
            self._asr.stop_and_transcribe()

    def _mirror_turn_shadow(self, method_name: str, *args, **kwargs) -> None:
        try:
            shadow = getattr(self, "_turn_shadow", None)
            if shadow is not None:
                getattr(shadow, method_name)(*args, **kwargs)
        except Exception:
            pass

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
        self._mirror_turn_shadow(
            "submit_asr_final",
            text,
            agent_playing=self._is_tts_guard_active,
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

    def _asr_preroll(self, bus_snapshot: list[bytes]) -> list[bytes]:
        return list(bus_snapshot[-CONFIG.asr_preroll_frames:])

    def _arm_asr_max_recording_deadline(self) -> None:
        self._asr_deadline = time.monotonic() + CONFIG.asr_max_recording_sec

    def _poll_followup_control(self) -> None:
        if not self._followup_control_path.exists():
            return
        try:
            mtime = self._followup_control_path.stat().st_mtime
        except OSError as exc:
            logger.warning("follow-up control stat failed: %s", exc)
            return
        if mtime == self._followup_control_mtime:
            return
        self._followup_control_mtime = mtime

        try:
            payload = json.loads(self._followup_control_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("follow-up control parse failed: %s", exc)
            return

        command = str(payload.get("command", "")).strip().lower()
        if command == "open":
            if not self._followup_enable:
                return
            session_id = str(payload.get("session_id", "")).strip()
            if not session_id:
                logger.warning("follow-up control open missing session_id")
                return
            try:
                updated_at = float(payload.get("updated_at", 0.0))
            except (TypeError, ValueError):
                updated_at = 0.0
            if updated_at and updated_at < self._started_at:
                logger.info("ignoring stale follow-up control for session=%s", session_id)
                return
            try:
                timeout_sec = float(payload.get("timeout_sec", _env_float("LLM_FOLLOWUP_TIMEOUT_SEC", 20.0)))
            except (TypeError, ValueError):
                timeout_sec = _env_float("LLM_FOLLOWUP_TIMEOUT_SEC", 20.0)
            reason = str(payload.get("reason", "control")).strip() or "control"
            self._open_followup_window(session_id, timeout_sec, reason)
        elif command == "close":
            reason = str(payload.get("reason", "control")).strip() or "control"
            self._close_followup_window(reason)

    def _open_followup_window(self, session_id: str, timeout_sec: float, reason: str) -> None:
        if timeout_sec <= 0:
            self._close_followup_window("non_positive_timeout")
            return
        self._followup_session_id = session_id
        self._vad.reset()
        self._followup_until = time.monotonic() + timeout_sec
        logger.info("follow-up window open: session=%s timeout=%.1fs reason=%s", session_id, timeout_sec, reason)
        self._set_wake_light_red("followup_window_open")
        if self._session_log:
            self._session_log.record(
                "followup_open",
                session_id=session_id,
                timeout_sec=timeout_sec,
                reason=reason,
            )

    def _close_followup_window(self, reason: str) -> None:
        if not self._followup_session_id and not self._followup_until:
            return
        session_id = self._followup_session_id
        self._followup_session_id = ""
        self._followup_until = 0.0
        logger.info("follow-up window closed: session=%s reason=%s", session_id or "default", reason)
        if reason not in ("new_wake", "followup_asr_started"):
            self._set_wake_light_blue(f"followup_window_closed:{reason}")
        if reason == "timeout":
            self._write_standby_ack_event(session_id or self._session_id or "default", "followup_timeout")
        if self._session_log:
            self._session_log.record("followup_closed", session_id=session_id or self._session_id or "default", reason=reason)

    def _followup_active(self) -> bool:
        if not self._followup_enable or not self._followup_session_id:
            return False
        if self._followup_guard_until and time.monotonic() < self._followup_guard_until:
            return False
        if time.monotonic() <= self._followup_until:
            return True
        self._close_followup_window("timeout")
        return False

    def _start_followup_recording(self) -> None:
        if not self._followup_session_id:
            return
        if self._is_tts_guard_active():
            logger.info("follow-up recording suppressed by tts guard")
            return
        self._session_id = self._followup_session_id
        self._close_followup_window("followup_asr_started")
        self._session_id = self._session_id or self._followup_session_id
        self._session_log = self._pipeline_logger.attach_session(self._session_id)
        bus_snapshot = self._bus.get_buffer()
        asr_preroll = self._asr_preroll(bus_snapshot)
        self._recording = True
        self._asr_audio_frames = asr_preroll
        self._asr.start_recording(initial_audio=b"".join(asr_preroll))
        self._vprint.start_capture(initial_audio=b"".join(bus_snapshot))
        self._asr_t0 = time.monotonic()
        self._arm_asr_max_recording_deadline()
        self._vad_holdoff_until = time.monotonic() + CONFIG.vad_holdoff_sec
        logger.info("follow-up asr started: session=%s", self._session_id)
        if self._session_log:
            self._session_log.record(
                "followup_asr_started",
                session_id=self._session_id,
                max_recording_sec=CONFIG.asr_max_recording_sec,
            )

    def _is_tts_guard_active(self) -> bool:
        if not self._tts_guard_enable:
            return False
        if not self._tts_guard_path.exists():
            return False
        try:
            payload = json.loads(self._tts_guard_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("tts guard read failed: %s", exc)
            return False
        if bool(payload.get("active", False)):
            return True
        try:
            guard_until = float(payload.get("guard_until", 0.0))
        except (TypeError, ValueError):
            guard_until = 0.0
        return time.time() < guard_until

    def _write_wake_light_command(
        self,
        color_name: str,
        red: int,
        green: int,
        blue: int,
        effect: str = "solid",
        reason: str = "",
    ) -> None:
        try:
            path = _wake_light_command_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "color": color_name,
                "red": red,
                "green": green,
                "blue": blue,
                "effect": effect,
                "reason": reason,
                "updated_at": time.time(),
            }
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            logger.info("wake light %s written for %s", color_name, reason or "unspecified")
        except Exception as exc:
            logger.warning("wake light command write failed: %s", exc)

    def _set_wake_light_red(self, reason: str = "") -> None:
        self._write_wake_light_command("red", 255, 0, 0, reason=reason)

    def _set_wake_light_blue(self, reason: str = "") -> None:
        self._write_wake_light_command("blue", 0, 0, 255, reason=reason)

    def _write_standby_ack_event(self, session_id: str, reason: str) -> None:
        try:
            self._standby_ack_event_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "event": "standby_ack",
                "reason": reason,
                "session_id": session_id,
                "updated_at": time.time(),
            }
            self._standby_ack_event_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("standby_ack_event written reason=%s session=%s", reason, session_id)
        except Exception as exc:
            logger.warning("standby ack event write failed: %s", exc)

    def _new_session(self, wake_word: str) -> str:
        session = self._pipeline_logger.start_session(wake_word)
        self._session_log = session
        self._session_id = session.session_id
        self._mirror_turn_shadow("close")
        self._turn_shadow = None
        try:
            self._turn_shadow = TurnShadowRuntime(
                session_log=session,
                enabled=_env_bool("TURN_SHADOW_ENABLE", False),
            )
        except Exception:
            pass
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
