from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String

from pipeline_log.pipeline_logger import PipelineLogger, SessionLog
from project_config import CONFIG


HTTP_SESSION = requests.Session()
HTTP_SESSION.trust_env = False


@dataclass
class SurfContext:
    wake_word: str = ""
    wake_time: float = 0.0
    vad_is_speech: bool = False
    vad_time: float = 0.0
    speaker: str = ""
    speaker_score: float = 0.0
    speaker_time: float = 0.0


class QwenSurfContextNode(Node):
    """Consume SURF context topics and run the qwen reply/TTS/action backend."""

    def __init__(self) -> None:
        super().__init__("qwen_surf_context_node")
        self.force_always_listen = CONFIG.always_listen
        self.awaiting_command_after_wake = False
        self.surf_context = SurfContext()
        self.status: dict[str, Any] = {
            "pipeline": "surf_qwen_workspace",
            "reply_backend": os.environ.get("QWEN_REPLY_BACKEND", "local"),
            "action_execute": CONFIG.action_execute,
            "action_release_after_sec": CONFIG.action_release_after_sec,
            "last_error": "",
            "latency": {},
        }
        self._status_lock = threading.Lock()
        self._action_lock = threading.Lock()
        self._tts_lock = threading.Lock()
        self._wake_state_lock = threading.Lock()
        self._wake_light_lock = threading.Lock()
        self._wake_light_client: Any | None = None
        self._last_wake_ack_at = 0.0
        self._wake_listen_until = 0.0
        self._wake_listen_generation = 0
        self._wake_command_started = False
        self._pipeline_lock = threading.Lock()
        self._pipeline_logger = PipelineLogger()
        self._session_log: SessionLog | None = None
        self._session_id = ""

        self.create_subscription(String, CONFIG.ros_audio_topic, self.on_audio_msg, 10)
        self.create_subscription(String, CONFIG.surf_wake_topic, self.on_wake, 10)
        self.create_subscription(Bool, CONFIG.surf_vad_topic, self.on_vad, 10)
        self.create_subscription(String, CONFIG.surf_speaker_topic, self.on_speaker, 10)

        CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._update_status(
            service_state="ready",
            qwen_server_url=CONFIG.qwen_server_url,
            action_backend=CONFIG.action_backend,
            action_keyword_first=CONFIG.action_keyword_first,
        )
        self.get_logger().info("Qwen SURF context node ready.")
        self.get_logger().info(f"SURF ASR topic: {CONFIG.ros_audio_topic}")
        self.get_logger().info(f"SURF wake topic: {CONFIG.surf_wake_topic}")
        self.get_logger().info(f"SURF VAD topic: {CONFIG.surf_vad_topic}")
        self.get_logger().info(f"SURF speaker topic: {CONFIG.surf_speaker_topic}")
        self.get_logger().info(f"Qwen server: {CONFIG.qwen_server_url}")
        self.get_logger().info(
            "Reply action bridge: "
            f"enabled={CONFIG.action_enable}, execute={CONFIG.action_execute}, "
            f"backend={CONFIG.action_backend}, network={CONFIG.unitree_network_interface}"
        )
        self.get_logger().info(
            "Qwen wake filter: "
            + ("disabled; SURF wake-word gates ASR." if self.force_always_listen else "enabled as a second filter.")
        )

    def on_wake(self, msg: String) -> None:
        payload = self._decode_json_payload(msg.data)
        wake_word = str(payload.get("word", msg.data)).strip()
        session_id = str(payload.get("session_id", "")).strip()
        self._attach_session(session_id or None)
        self.surf_context.wake_word = wake_word
        self.surf_context.wake_time = time.time()
        self._write_status()
        self._update_status(last_wake=wake_word, last_wake_time=self.surf_context.wake_time)
        self._session_record("wake_received", wake_word=wake_word, session_id=self._session_id)
        self.get_logger().info(f"SURF wake detected: {wake_word} session={self._session_id}")
        self._open_wake_listen_window()
        self._maybe_play_wake_ack(wake_word)

    def on_vad(self, msg: Bool) -> None:
        self.surf_context.vad_is_speech = bool(msg.data)
        self.surf_context.vad_time = time.time()
        if self.surf_context.vad_is_speech:
            self._mark_wake_command_started()
        self._write_status()
        self.get_logger().debug(f"SURF VAD: {self.surf_context.vad_is_speech}")

    def on_speaker(self, msg: String) -> None:
        speaker = ""
        score = 0.0
        try:
            payload = json.loads(msg.data)
            speaker = str(payload.get("speaker", "")).strip()
            score = float(payload.get("score", 0.0))
        except Exception:
            speaker = msg.data.strip()

        if speaker:
            self.surf_context.speaker = speaker
            self.surf_context.speaker_score = score
            self.surf_context.speaker_time = time.time()
            self._write_status()
            self._update_status(
                last_speaker=speaker,
                last_speaker_score=score,
                last_speaker_time=self.surf_context.speaker_time,
            )
            self.get_logger().info(f"SURF speaker: {speaker} score={score:.3f}")

    def on_audio_msg(self, msg: String) -> None:
        received_at = time.time()
        raw = msg.data
        speaker_from_audio = ""
        confidence: float | None = None
        session_id = ""
        try:
            data = json.loads(raw)
            user_text = str(data.get("text", "")).strip()
            speaker_from_audio = str(data.get("speaker", "")).strip()
            session_id = str(data.get("session_id", "")).strip()
            if "confidence" in data:
                confidence = float(data.get("confidence", 0.0))
        except Exception:
            user_text = raw.strip()

        if speaker_from_audio:
            self.surf_context.speaker = speaker_from_audio
            self.surf_context.speaker_time = time.time()

        if not user_text:
            if session_id:
                self._attach_session(session_id)
            self._close_wake_listen_window("empty_asr")
            self._set_wake_light_blue()
            return

        self._attach_session(session_id or None)
        self._session_record(
            "asr_received",
            text=user_text,
            speaker=self.surf_context.speaker,
            session_id=self._session_id,
        )

        ignore_reason = self._asr_ignore_reason(user_text, confidence)
        if ignore_reason:
            self.get_logger().warn(f"Ignoring ASR text: reason={ignore_reason}, text={user_text}")
            self._update_status(
                last_ignored_asr=user_text,
                last_ignored_asr_reason=ignore_reason,
                last_error=f"ignored_asr:{ignore_reason}",
                updated_at=time.time(),
            )
            self._close_wake_listen_window(f"ignored_asr:{ignore_reason}")
            self._set_wake_light_blue()
            return

        self.get_logger().info(
            f"SURF ASR text: {user_text}"
            + (f" speaker={self.surf_context.speaker}" if self.surf_context.speaker else "")
        )
        self._update_status(
            last_asr=user_text,
            last_asr_time=received_at,
            last_audio_confidence=confidence,
            last_error="",
            latency={
                **self.status.get("latency", {}),
                "wake_to_asr_ms": self._elapsed_ms(self.surf_context.wake_time, received_at),
            },
        )

        if not self.force_always_listen:
            command_text = self.strip_wake_word(user_text)
            if command_text is None:
                if not self._consume_wake_listen_window():
                    self.get_logger().info("Second qwen wake filter did not match; ignoring ASR text.")
                    return
                command_text = user_text.strip()
            elif not command_text:
                self._open_wake_listen_window()
                self.get_logger().info(
                    "Second qwen wake filter matched. Waiting for the next ASR command event."
                )
                return
            user_text = command_text

        qwen_text = self._build_qwen_text(user_text)
        request_session_id = self._session_id or session_id or self._fallback_session_id()
        qwen_started_at = time.time()
        self._set_wake_light_green()
        self._session_record("thinking", text=user_text, session_id=request_session_id)
        self._run_thinking_action()
        self._maybe_play_thinking_ack(request_session_id)
        qwen_response = self._request_qwen(qwen_text, session_id=request_session_id)
        qwen_finished_at = time.time()
        reply = str(qwen_response.get("reply", "")).strip()
        action_payload = qwen_response.get("action", {})
        if not reply:
            self._update_status(last_error="llm_request_failed", updated_at=time.time())
            self._session_record("llm_failed", session_id=request_session_id)
            self._set_wake_light_blue()
            self._close_session("session_end")
            return

        self.get_logger().info(f"LLM reply: {reply}")
        timing = qwen_response.get("timing", {})
        self._update_status(
            last_reply=reply,
            last_reply_time=qwen_finished_at,
            latency={
                **self.status.get("latency", {}),
                "llm_ms": self._elapsed_ms(qwen_started_at, qwen_finished_at),
                "wake_to_reply_ms": self._elapsed_ms(self.surf_context.wake_time, qwen_finished_at),
            },
        )
        self._session_record(
            "llm_reply",
            reply=reply,
            session_id=request_session_id,
            timing=timing,
        )

        tts_started_at = time.time()
        try:
            tts_ok = self._prepare_tts_wav("reply", reply, session_id=request_session_id)
        except Exception as exc:
            self.get_logger().warn(f"Reply TTS request failed: {exc}")
            tts_ok = False
        if not tts_ok:
            self._update_status(last_error="tts_wav_failed", updated_at=time.time())
            self._session_record("tts_failed", session_id=request_session_id)
            self._set_wake_light_blue()
            self._close_session("session_end")
            return
        self._update_status(
            last_tts_wav=str(CONFIG.tts_wav_path),
            last_tts_time=time.time(),
            latency={
                **self.status.get("latency", {}),
                "tts_convert_ms": self._elapsed_ms(tts_started_at, time.time()),
            },
        )
        self._session_record("tts_ready", session_id=request_session_id, text=reply)
        action_thread = threading.Thread(
            target=self.run_reply_action,
            args=(reply, user_text, action_payload),
            daemon=True,
        )
        action_thread.start()

    @staticmethod
    def strip_wake_word(text: str) -> str | None:
        lowered_text = text.lower()
        for wake_word in CONFIG.wake_words:
            index = lowered_text.find(wake_word.lower())
            if index < 0:
                continue
            prefix = text[:index]
            suffix = text[index + len(wake_word):]
            return (prefix + suffix).strip("，,。.!！?？ ")

        compact_text = text.replace(" ", "")
        for wake_word in CONFIG.wake_words:
            compact_wake = wake_word.replace(" ", "")
            index = compact_text.lower().find(compact_wake.lower())
            if index < 0:
                continue
            prefix = compact_text[:index]
            suffix = compact_text[index + len(compact_wake):]
            return (prefix + suffix).strip("，,。.!！?？ ")

        return None

    def _open_wake_listen_window(self) -> None:
        with self._wake_state_lock:
            self.awaiting_command_after_wake = True
            self._wake_listen_until = 0.0
            self._wake_listen_generation += 1
            self._wake_command_started = False

        self._update_status(
            wake_listen_active=True,
            wake_listen_until=None,
            wake_listen_sec=None,
        )
        threading.Thread(target=self._set_wake_light_red, daemon=True).start()

    def _consume_wake_listen_window(self) -> bool:
        with self._wake_state_lock:
            if not self.awaiting_command_after_wake:
                return False
            self.awaiting_command_after_wake = False
            self._wake_listen_until = 0.0
            self._wake_command_started = False
            close_reason = "command_received"

        self._update_status(wake_listen_active=False, last_wake_listen_closed_reason=close_reason)
        self._session_record("wake_listen_closed", reason=close_reason, session_id=self._session_id)
        return True

    def _expire_wake_listen_window(self, generation: int) -> None:
        """Legacy timeout hook kept unused; wake state is now closed by events."""
        return

    def _mark_wake_command_started(self) -> None:
        should_record = False
        with self._wake_state_lock:
            if not self.awaiting_command_after_wake:
                return
            if not self._wake_command_started:
                self._wake_command_started = True
                should_record = True

        if should_record:
            self._update_status(wake_command_started=True, wake_command_started_time=time.time())
            self._session_record("wake_command_started", session_id=self._session_id)

    def _close_wake_listen_window(self, reason: str) -> None:
        with self._wake_state_lock:
            if not self.awaiting_command_after_wake:
                return
            self.awaiting_command_after_wake = False
            self._wake_listen_until = 0.0
            self._wake_command_started = False

        self._update_status(wake_listen_active=False, last_wake_listen_closed_reason=reason)
        self._session_record("wake_listen_closed", reason=reason, session_id=self._session_id)

    @staticmethod
    def _elapsed_ms(start: float, end: float) -> int | None:
        if not start:
            return None
        return int((end - start) * 1000)

    def _asr_ignore_reason(self, text: str, confidence: float | None) -> str:
        if not CONFIG.filter_bad_asr:
            return ""
        stripped = text.strip()
        if not stripped:
            return "empty"
        if confidence is not None and confidence < CONFIG.min_audio_confidence:
            return f"low_confidence_{confidence:.2f}"
        meaningful = re.sub(r"[\s，。！？、,.!?;:：；'\"“”‘’\-()（）\[\]{}]", "", stripped)
        if len(meaningful) < CONFIG.min_asr_chars:
            return "too_short"
        if not re.search(r"[\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]", meaningful):
            return "punctuation_only"
        lowered = stripped.lower()
        english_tokens = re.findall(r"[a-z]+", lowered)
        if english_tokens and not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", stripped):
            token_set = set(english_tokens)
            filler_tokens = {"the", "oe", "uh", "um", "er", "ah"}
            if token_set <= filler_tokens:
                return "english_filler"
        return ""

    def _build_qwen_text(self, user_text: str) -> str:
        if CONFIG.reply_backend == "rag":
            return user_text
        if not CONFIG.include_speaker_context or not self.surf_context.speaker:
            return user_text

        return (
            f"系统上下文：当前说话人是{self.surf_context.speaker}。"
            "除非用户询问身份或上下文，否则不要在回复中复述这句系统上下文。"
            f"\n用户说：{user_text}"
        )

    def _fallback_session_id(self) -> str:
        speaker = self.surf_context.speaker.strip() if self.surf_context.speaker else "default"
        return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", speaker) or "default"

    def _request_qwen(self, text: str, session_id: str = "default") -> dict[str, Any]:
        try:
            response = HTTP_SESSION.get(
                CONFIG.qwen_server_url,
                params={"text": text, "session_id": session_id},
                timeout=CONFIG.request_timeout_sec,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            self.get_logger().error(f"Qwen request failed: {exc}")
            return {}

        reply = str(result.get("reply", "")).strip()
        if not reply:
            self.get_logger().error("Empty reply from Qwen")
        result["reply"] = reply
        return result

    def _maybe_play_wake_ack(self, wake_word: str) -> None:
        ack_text = self._wake_ack_text(wake_word)
        if not CONFIG.wake_ack_enable or not ack_text:
            return
        now = time.monotonic()
        if now - self._last_wake_ack_at < CONFIG.wake_ack_cooldown_sec:
            return
        self._last_wake_ack_at = now
        threading.Thread(target=self._play_wake_ack, args=(ack_text,), daemon=True).start()

    @staticmethod
    def _wake_ack_text(wake_word: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", wake_word):
            return CONFIG.wake_ack_text_zh
        if re.search(r"[A-Za-z]", wake_word):
            return CONFIG.wake_ack_text_en
        return CONFIG.wake_ack_text

    def _set_wake_light_red(self) -> None:
        self._set_wake_light_color("red", 255, 0, 0)

    def _set_wake_light_green(self) -> None:
        self._set_wake_light_color("green", 0, 255, 0)

    def _set_wake_light_blue(self) -> None:
        self._set_wake_light_color("blue", 0, 0, 255)

    def _write_tts_play_context(self, kind: str, text: str = "", session_id: str = "") -> None:
        try:
            payload = {
                "kind": kind,
                "text": text,
                "session_id": session_id or self._session_id or "default",
                "updated_at": time.time(),
            }
            CONFIG.tts_play_context_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self.get_logger().warn(f"TTS play context write failed: {exc}")

    def _request_tts_mp3(self, text: str) -> None:
        response = HTTP_SESSION.get(
            self._qwen_tts_url(),
            params={"text": text},
            timeout=CONFIG.request_timeout_sec,
        )
        response.raise_for_status()

    def _prepare_tts_wav(self, kind: str, text: str, session_id: str = "") -> bool:
        with self._tts_lock:
            self._write_tts_play_context(kind, text, session_id=session_id)
            self._request_tts_mp3(text)
            return self._convert_tts_to_wav()

    def _set_wake_light_color(
        self,
        color_name: str,
        red: int,
        green: int,
        blue: int,
        effect: str = "solid",
    ) -> None:
        if not CONFIG.unitree_enable:
            self._update_status(last_wake_light="skipped_unitree_disabled")
            return
        try:
            payload = {
                "color": color_name,
                "red": red,
                "green": green,
                "blue": blue,
                "effect": effect,
                "updated_at": time.time(),
            }
            CONFIG.wake_light_command_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self.get_logger().warn(f"Wake light command {color_name} failed: {exc}")
            self._update_status(last_error="wake_light_failed", updated_at=time.time())
            return

        self.get_logger().info(f"Wake light command queued: {color_name}.")
        self._update_status(last_wake_light=color_name, last_wake_light_time=time.time())

    def _maybe_play_thinking_ack(self, session_id: str) -> None:
        if not CONFIG.thinking_ack_enable:
            return
        ack_text = CONFIG.thinking_ack_text.strip()
        if not ack_text:
            return
        self._play_thinking_ack(ack_text, session_id)

    def _play_thinking_ack(self, ack_text: str, session_id: str) -> None:
        started_at = time.time()
        try:
            tts_ok = self._prepare_tts_wav("thinking_ack", ack_text, session_id=session_id)
        except Exception as exc:
            self.get_logger().warn(f"Thinking ack TTS request failed: {exc}")
            self._session_record("thinking_ack_failed", text=ack_text, reason=str(exc), session_id=session_id)
            return

        if not tts_ok:
            self._session_record("thinking_ack_failed", text=ack_text, reason="wav_failed", session_id=session_id)
            return

        self.get_logger().info(f"Thinking ack played: {ack_text}")
        self._session_record(
            "thinking_ack_ready",
            text=ack_text,
            session_id=session_id,
            duration_ms=self._elapsed_ms(started_at, time.time()),
        )

    def _play_wake_ack(self, ack_text: str) -> None:
        started_at = time.time()
        try:
            self._write_tts_play_context("wake_ack", ack_text)
            response = HTTP_SESSION.get(
                self._qwen_tts_url(),
                params={"text": ack_text},
                timeout=CONFIG.request_timeout_sec,
            )
            response.raise_for_status()
        except Exception as exc:
            self.get_logger().warn(f"Wake ack TTS request failed: {exc}")
            self._update_status(last_error="wake_ack_tts_failed", updated_at=time.time())
            return

        if not self._convert_tts_to_wav_locked():
            self._update_status(last_error="wake_ack_wav_failed", updated_at=time.time())
            return

        self._run_wake_ack_action()
        self.get_logger().info(f"Wake ack played: {ack_text}")
        self._update_status(
            last_wake_ack=ack_text,
            last_wake_ack_time=time.time(),
            latency={
                **self.status.get("latency", {}),
                "wake_ack_ms": self._elapsed_ms(started_at, time.time()),
            },
        )
        self._session_record("wake_ack_ready", text=ack_text, session_id=self._session_id)

    def _run_wake_ack_action(self) -> None:
        if not CONFIG.wake_ack_action_enable:
            self._session_record("wake_ack_action_skipped", reason="disabled", session_id=self._session_id)
            return
        if not CONFIG.action_enable:
            self._session_record("wake_ack_action_skipped", reason="action_disabled", session_id=self._session_id)
            return
        if not CONFIG.action_execute:
            self._session_record(
                "wake_ack_action_skipped",
                reason="execute_disabled",
                action_id=CONFIG.wake_ack_action_id,
                label=CONFIG.wake_ack_action_label,
                session_id=self._session_id,
            )
            return
        if not self._action_lock.acquire(blocking=False):
            self.get_logger().warn("Skipping wake ack action because another action is still running.")
            self._session_record("wake_ack_action_skipped", reason="busy", session_id=self._session_id)
            return

        threading.Thread(target=self._run_wake_ack_action_locked, daemon=True).start()

    def _run_wake_ack_action_locked(self) -> None:
        started_at = time.time()
        try:
            command = [
                str(CONFIG.action_runner),
                "--network",
                CONFIG.unitree_network_interface,
                "--id",
                str(CONFIG.wake_ack_action_id),
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=20,
                    env=self.action_env(),
                )
            except Exception as exc:
                self.get_logger().error(f"Wake ack action failed: {exc}")
                self._session_record(
                    "wake_ack_action_result",
                    label=CONFIG.wake_ack_action_label,
                    action_id=CONFIG.wake_ack_action_id,
                    executed=False,
                    reason=str(exc),
                    session_id=self._session_id,
                )
                return

            if completed.stdout:
                self.get_logger().info(f"Wake ack action stdout: {completed.stdout.strip()}")
            if completed.stderr:
                self.get_logger().warn(f"Wake ack action stderr: {completed.stderr.strip()}")

            executed = completed.returncode == 0
            reason = "runner_completed" if executed else f"runner_exit_{completed.returncode}"
            self.get_logger().info(
                f"Wake ack action: {CONFIG.wake_ack_action_label} "
                f"id={CONFIG.wake_ack_action_id} executed={executed} reason={reason}"
            )
            self._update_status(
                last_wake_ack_action=CONFIG.wake_ack_action_label,
                last_wake_ack_action_id=CONFIG.wake_ack_action_id,
                last_wake_ack_action_executed=executed,
                last_wake_ack_action_reason=reason,
                last_wake_ack_action_time=time.time(),
                latency={
                    **self.status.get("latency", {}),
                    "wake_ack_action_ms": self._elapsed_ms(started_at, time.time()),
                },
            )
            self._session_record(
                "wake_ack_action_result",
                label=CONFIG.wake_ack_action_label,
                official_name="face wave",
                action_id=CONFIG.wake_ack_action_id,
                executed=executed,
                reason=reason,
                session_id=self._session_id,
            )
        finally:
            self._action_lock.release()

    def _run_thinking_action(self) -> None:
        threading.Thread(target=self._run_thinking_action_script, daemon=True).start()

    def _run_thinking_action_script(self) -> None:
        script = (
            CONFIG.project_root
            / "deps"
            / "qwen_ros_node_edg_tts"
            / "third_party"
            / "unitree_sdk2_python"
            / "g1"
            / "high_level"
            / "g1_arm7_sdk_dds_example.py"
        )
        try:
            subprocess.run(
                [
                    os.environ.get("QWEN_PYTHON", "python3"),
                    str(script),
                    CONFIG.unitree_network_interface,
                ],
                input="\n",
                text=True,
                check=False,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().warn(f"Thinking action failed: {exc}")

    @staticmethod
    def _qwen_tts_url() -> str:
        return CONFIG.qwen_server_url.rsplit("/", 1)[0] + "/tts"

    def _convert_tts_to_wav_locked(self) -> bool:
        with self._tts_lock:
            return self._convert_tts_to_wav()

    def _convert_tts_to_wav(self) -> bool:
        if not CONFIG.tts_mp3_path.exists():
            self.get_logger().error(f"{CONFIG.tts_mp3_path} not found; Qwen server did not generate it")
            return False

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(CONFIG.tts_mp3_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(CONFIG.tts_wav_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self.get_logger().error(f"ffmpeg conversion failed: {exc}")
            return False

        if not CONFIG.tts_wav_path.exists():
            self.get_logger().error(f"{CONFIG.tts_wav_path} not generated")
            return False

        self.get_logger().info(f"TTS wav generated successfully: {CONFIG.tts_wav_path}")
        return True

    def run_reply_action(
        self,
        reply: str,
        user_text: str = "",
        action_payload: dict[str, Any] | None = None,
    ) -> None:
        if not CONFIG.action_enable:
            self._session_record("action_skipped", reason="action_disabled", reply=reply)
            self._close_session("session_end")
            return
        if not self._action_lock.acquire(blocking=False):
            self.get_logger().warn("Skipping reply action because another action is still running.")
            self._update_status(last_error="action_busy", updated_at=time.time())
            self._session_record("action_skipped", reason="busy", reply=reply)
            self._close_session("session_end")
            return

        try:
            self._run_reply_action_locked(reply, user_text, action_payload)
        finally:
            self._action_lock.release()
            self._close_session("session_end")

    def _run_reply_action_locked(
        self,
        reply: str,
        user_text: str = "",
        action_payload: dict[str, Any] | None = None,
    ) -> None:
        started_at = time.time()
        payload: dict[str, Any] | None = None
        command: list[str] = []

        if action_payload:
            classification = self._classification_from_deepseek_action(action_payload, reply)
            execution = self._execute_classified_action(classification)
            command = self._runner_command(classification.get("action_id"))
            payload = {"classification": classification, "execution": execution}

        if payload is None and CONFIG.action_keyword_first and user_text:
            user_payload = self._run_action_classifier(user_text, "keyword")
            if user_payload:
                user_classification = user_payload.get("classification", {})
                if self._int_or_default(user_classification.get("action_id"), -1) >= 0:
                    payload = user_payload
                    command = self._action_command(user_text, "keyword")

        if payload is None and CONFIG.action_backend not in ("deepseek", "none"):
            payload = self._run_action_classifier(reply, CONFIG.action_backend)
            command = self._action_command(reply, CONFIG.action_backend)

        if payload is None:
            classification = self._no_action_classification(reply, "no_deepseek_action")
            execution = {"executed": False, "reason": "no_action_payload"}
            self._log_action_result(classification, execution, started_at, command, reply)
            return

        classification = payload.get("classification", {})
        execution = payload.get("execution", {})
        self._log_action_result(classification, execution, started_at, command, reply)

    def _classification_from_deepseek_action(self, action_payload: dict[str, Any], reply: str) -> dict[str, Any]:
        allowed = {
            "无动作": ("none", -1),
            "释放手臂": ("release arm", 99),
            "双手飞吻": ("two-hand kiss", 11),
            "右手飞吻": ("right kiss", 13),
            "左手飞吻": ("left kiss", 12),
            "举双手": ("hands up", 15),
            "鼓掌": ("clap", 17),
            "击掌": ("high five", 18),
            "拥抱": ("hug", 19),
            "比心": ("heart", 20),
            "右手比心": ("right heart", 21),
            "拒绝摆手": ("reject", 22),
            "举右手": ("right hand up", 23),
            "x-ray": ("x-ray", 24),
            "面前挥手": ("face wave", 25),
            "高位挥手": ("high wave", 26),
            "握手": ("shake hand", 27),
        }
        label = str(action_payload.get("label", "无动作")).strip()
        if label not in allowed:
            label = "无动作"
            reason = "DeepSeek returned an action outside the whitelist."
        else:
            reason = str(action_payload.get("reason", "")).strip()

        try:
            score = float(action_payload.get("score", action_payload.get("confidence", 0.0)))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        official_name, action_id = allowed[label]
        should_execute = action_id >= 0 and score >= CONFIG.action_threshold
        return {
            "text": reply,
            "label": label,
            "official_name": official_name,
            "action_id": action_id,
            "score": score,
            "backend": "deepseek",
            "should_execute": should_execute,
            "reason": reason,
        }

    def _no_action_classification(self, reply: str, reason: str) -> dict[str, Any]:
        return {
            "text": reply,
            "label": "无动作",
            "official_name": "none",
            "action_id": -1,
            "score": 0.0,
            "backend": "deepseek",
            "should_execute": False,
            "reason": reason,
        }

    def _runner_command(self, action_id: Any) -> list[str]:
        return [
            str(CONFIG.action_runner),
            "--network",
            CONFIG.unitree_network_interface,
            "--id",
            str(action_id),
        ]

    def _execute_classified_action(self, classification: dict[str, Any]) -> dict[str, Any]:
        action_id = self._int_or_default(classification.get("action_id"), -1)
        if action_id < 0:
            return {"executed": False, "reason": "unknown_action"}
        if not classification.get("should_execute"):
            return {"executed": False, "reason": "score_below_threshold"}
        if not CONFIG.action_execute:
            return {"executed": False, "reason": "dry_run", "would_run": self._runner_command(action_id)}
        if not CONFIG.unitree_network_interface:
            return {"executed": False, "reason": "--network is required"}
        if not CONFIG.action_runner.exists():
            return {"executed": False, "reason": f"runner not found: {CONFIG.action_runner}"}

        command = self._runner_command(action_id)
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=90,
                env=self.action_env(),
            )
        except Exception as exc:
            return {"executed": False, "reason": str(exc), "command": command}

        output = completed.stdout + completed.stderr
        if "The actions are only supported in fsm id" in output:
            reason = "invalid_fsm_id"
        elif "The arm is holding" in output:
            reason = "arm_holding_release_required"
        elif "Execute action failed" in output or "Invalid action id" in output:
            reason = "runner_reported_failure"
        elif completed.returncode != 0:
            reason = "runner_nonzero_returncode"
        else:
            reason = "runner_completed"

        return {
            "executed": completed.returncode == 0,
            "reason": reason,
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    def _log_action_result(
        self,
        classification: dict[str, Any],
        execution: dict[str, Any],
        started_at: float,
        command: list[str],
        reply: str,
    ) -> None:
        if (
            CONFIG.action_keyword_first
            and CONFIG.action_backend != "keyword"
            and classification.get("label") == "无动作"
            and classification.get("backend") == "qwen"
        ):
            keyword_payload = self._run_action_classifier(reply, "keyword")
            if keyword_payload:
                keyword_classification = keyword_payload.get("classification", {})
                keyword_execution = keyword_payload.get("execution", {})
                if self._int_or_default(keyword_classification.get("action_id"), -1) >= 0:
                    classification = keyword_classification
                    execution = keyword_execution

        self.get_logger().info(
            "Reply action: "
            f"{classification.get('label')} / {classification.get('official_name')} "
            f"id={classification.get('action_id')} "
            f"score={classification.get('score')} "
            f"backend={classification.get('backend')} "
            f"executed={execution.get('executed')} "
            f"reason={execution.get('reason')}"
        )
        self._update_status(
            last_action=classification.get("label"),
            last_action_id=classification.get("action_id"),
            last_action_score=classification.get("score"),
            last_action_backend=classification.get("backend"),
            last_action_executed=execution.get("executed"),
            last_action_reason=execution.get("reason"),
            last_action_time=time.time(),
            latency={
                **self.status.get("latency", {}),
                "action_ms": self._elapsed_ms(started_at, time.time()),
            },
        )
        self._session_record(
            "action_result",
            label=classification.get("label"),
            official_name=classification.get("official_name"),
            action_id=classification.get("action_id"),
            score=classification.get("score"),
            backend=classification.get("backend"),
            executed=execution.get("executed"),
            reason=execution.get("reason"),
            reply=reply,
        )

        if (
            CONFIG.action_auto_release
            and CONFIG.action_execute
            and execution.get("reason") == "arm_holding_release_required"
        ):
            self.get_logger().warn("Arm is holding; running release action 99 and retrying once.")
            if self.release_arm():
                if classification.get("backend") == "deepseek":
                    retry_execution = self._execute_classified_action(classification)
                    self.get_logger().info(
                        "Reply action retry: "
                        f"{classification.get('label')} id={classification.get('action_id')} "
                        f"executed={retry_execution.get('executed')} reason={retry_execution.get('reason')}"
                    )
                else:
                    self.retry_reply_action(command)
            return

        if (
            CONFIG.action_execute
            and CONFIG.action_release_after_sec > 0
            and execution.get("executed")
            and self._int_or_default(classification.get("action_id"), -1) not in (-1, 99)
        ):
            self.get_logger().info(
                f"Action completed; releasing arm in {CONFIG.action_release_after_sec:.1f}s."
            )
            time.sleep(CONFIG.action_release_after_sec)
            self.release_arm()

    @staticmethod
    def _int_or_default(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _action_command(self, reply: str, backend: str) -> list[str]:
        command = [
            CONFIG.action_python,
            str(CONFIG.action_script),
            reply,
            "--backend",
            backend,
            "--threshold",
            str(CONFIG.action_threshold),
            "--network",
            CONFIG.unitree_network_interface,
            "--runner",
            str(CONFIG.action_runner),
        ]
        if backend == "qwen" and not CONFIG.action_keyword_first:
            command.append("--no-keyword-first")
        if CONFIG.action_execute:
            command.append("--execute")
        return command

    def _run_action_classifier(self, reply: str, backend: str) -> dict[str, Any] | None:
        try:
            completed = subprocess.run(
                self._action_command(reply, backend),
                check=False,
                text=True,
                capture_output=True,
                timeout=90,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().warn(f"{backend} action classifier failed: {exc}")
            return None
        try:
            return json.loads(completed.stdout)
        except Exception:
            self.get_logger().warn(f"{backend} action classifier returned non-JSON: {completed.stdout.strip()}")
            return None

    @staticmethod
    def _decode_json_payload(raw: str) -> dict[str, Any]:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    def _attach_session(self, session_id: str | None) -> SessionLog | None:
        session_id = (session_id or "").strip()
        if not session_id:
            return self._session_log
        with self._pipeline_lock:
            if self._session_id == session_id and self._session_log is not None:
                return self._session_log
            self._session_id = session_id
            self._session_log = self._pipeline_logger.attach_session(session_id)
            return self._session_log

    def _session_record(self, stage: str, **kwargs: Any) -> None:
        session = self._session_log
        if session is None:
            return
        session.record(stage, **kwargs)

    def _close_session(self, reason: str = "session_end") -> None:
        session = self._session_log
        if session is None:
            return
        session.record(reason, session_id=self._session_id or "default")

    @staticmethod
    def action_env() -> dict[str, str]:
        env = os.environ.copy()
        env["NO_PROXY"] = "127.0.0.1,localhost," + env.get("NO_PROXY", "")
        env["no_proxy"] = "127.0.0.1,localhost," + env.get("no_proxy", "")
        sdk_root = CONFIG.action_runner.parent.parent.parent
        unitree_lib_dir = sdk_root / "thirdparty" / "lib" / os.uname().machine
        if unitree_lib_dir.is_dir():
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = str(unitree_lib_dir) + (f":{existing}" if existing else "")
        return env

    def release_arm(self) -> bool:
        try:
            completed = subprocess.run(
                [
                    str(CONFIG.action_runner),
                    "--network",
                    CONFIG.unitree_network_interface,
                    "--id",
                    "99",
                ],
                check=False,
                text=True,
                capture_output=True,
                timeout=20,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().error(f"Release arm action failed: {exc}")
            return False

        if completed.stdout:
            self.get_logger().info(f"Release arm stdout: {completed.stdout.strip()}")
        if completed.stderr:
            self.get_logger().warn(f"Release arm stderr: {completed.stderr.strip()}")
        ok = completed.returncode == 0
        self._update_status(last_release_arm_ok=ok, last_release_arm_time=time.time())
        return ok

    def retry_reply_action(self, command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                capture_output=True,
                timeout=90,
                env=self.action_env(),
            )
        except Exception as exc:
            self.get_logger().error(f"Reply action retry failed: {exc}")
            return

        try:
            payload = json.loads(completed.stdout)
        except Exception:
            self.get_logger().error(f"Reply action retry returned non-JSON output: {completed.stdout.strip()}")
            return

        classification = payload.get("classification", {})
        execution = payload.get("execution", {})
        self.get_logger().info(
            "Reply action retry: "
            f"{classification.get('label')} id={classification.get('action_id')} "
            f"executed={execution.get('executed')} reason={execution.get('reason')}"
        )

    def _write_status(self) -> None:
        if not CONFIG.write_context_status:
            return
        status_path = CONFIG.runtime_dir / "surf_context_status.json"
        payload: dict[str, Any] = asdict(self.surf_context)
        payload["updated_at"] = time.time()
        try:
            status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.get_logger().warn(f"Failed to write context status: {exc}")

    def _update_status(self, **updates: Any) -> None:
        if not CONFIG.write_context_status:
            return
        status_path = CONFIG.runtime_dir / "status.json"
        with self._status_lock:
            latency = updates.pop("latency", None)
            self.status.update(updates)
            if latency is not None:
                self.status["latency"] = latency
            self.status["surf_context"] = asdict(self.surf_context)
            self.status["updated_at"] = time.time()
            payload = json.dumps(self.status, ensure_ascii=False, indent=2)
        try:
            status_path.write_text(payload, encoding="utf-8")
        except OSError as exc:
            self.get_logger().warn(f"Failed to write pipeline status: {exc}")


def main() -> None:
    rclpy.init()
    node = QwenSurfContextNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
