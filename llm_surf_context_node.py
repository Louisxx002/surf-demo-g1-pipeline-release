from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import asdict, dataclass
from typing import Any

import requests
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String

from pipeline_control.interrupt import InterruptControl
from pipeline_log.pipeline_logger import PipelineLogger, SessionLog
from project_config import CONFIG
from reply_action_policy import is_explicit_action_request, resolve_reply_action
from text_command_policy import matches_command, normalize_command_text, select_terminate_ack_text


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


class LlmSurfContextNode(Node):
    """Consume SURF context topics and run the LLM reply/TTS/action backend."""

    def __init__(self) -> None:
        super().__init__("llm_surf_context_node")
        self.force_always_listen = CONFIG.always_listen
        self.awaiting_command_after_wake = False
        self.surf_context = SurfContext()
        self.status: dict[str, Any] = {
            "pipeline": "surf_llm_workspace",
            "reply_backend": CONFIG.reply_backend,
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
        self._wake_ack_guard_until = 0.0
        self._followup_until = 0.0
        self._followup_generation = 0
        self._conversation_session_id = ""
        self._pipeline_lock = threading.Lock()
        self._pipeline_logger = PipelineLogger()
        self._session_log: SessionLog | None = None
        self._session_id = ""
        self._standby_ack_event_mtime = 0.0
        self._standby_ack_event_updated_at = 0.0
        self._interrupt_control = InterruptControl(CONFIG.runtime_dir)
        self._last_session_command_request_id = str(
            self._interrupt_control.read_session_command().get("request_id", "")
        )

        self.create_subscription(String, CONFIG.ros_audio_topic, self.on_audio_msg, 10)
        self.create_subscription(String, CONFIG.surf_wake_topic, self.on_wake, 10)
        self.create_subscription(Bool, CONFIG.surf_vad_topic, self.on_vad, 10)
        self.create_subscription(String, CONFIG.surf_speaker_topic, self.on_speaker, 10)
        self.create_timer(0.2, self._poll_wake_listen_timeout)
        self.create_timer(0.2, self._poll_session_command)
        self.create_timer(0.3, self._poll_standby_ack_event)

        CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._update_status(
            service_state="ready",
            llm_server_url=CONFIG.llm_server_url,
            action_backend=CONFIG.action_backend,
            action_keyword_first=CONFIG.action_keyword_first,
            followup_enable=CONFIG.followup_enable,
            followup_timeout_sec=CONFIG.followup_timeout_sec,
            followup_control_file=str(CONFIG.followup_control_path),
            standby_ack_enable=CONFIG.standby_ack_enable,
            standby_ack_event_file=str(CONFIG.standby_ack_event_path),
            robot_skill_enable=CONFIG.robot_skill_enable,
            robot_skill_execute=CONFIG.robot_skill_execute,
            robot_skill_runner=str(CONFIG.robot_skill_runner),
        )
        self.get_logger().info("LLM SURF context node ready.")
        self.get_logger().info(f"SURF ASR topic: {CONFIG.ros_audio_topic}")
        self.get_logger().info(f"SURF wake topic: {CONFIG.surf_wake_topic}")
        self.get_logger().info(f"SURF VAD topic: {CONFIG.surf_vad_topic}")
        self.get_logger().info(f"SURF speaker topic: {CONFIG.surf_speaker_topic}")
        self.get_logger().info(f"LLM server: {CONFIG.llm_server_url}")
        self.get_logger().info(
            "Reply action bridge: "
            f"enabled={CONFIG.action_enable}, execute={CONFIG.action_execute}, "
            f"backend={CONFIG.action_backend}, network={CONFIG.unitree_network_interface}"
        )
        self.get_logger().info(
            "LLM wake filter: "
            + ("disabled; SURF wake-word gates ASR." if self.force_always_listen else "enabled as a second filter.")
        )
        threading.Thread(target=self._prewarm_wake_ack_cache, daemon=True).start()

    def on_wake(self, msg: String) -> None:
        payload = self._decode_json_payload(msg.data)
        wake_word = str(payload.get("word", msg.data)).strip()
        session_id = str(payload.get("session_id", "")).strip()
        self._interrupt_active_reply_for_wake(session_id)
        self._close_followup_window("new_wake")
        self._attach_session(session_id or None)
        self.surf_context.wake_word = wake_word
        self.surf_context.wake_time = time.time()
        self._write_status()
        self._update_status(last_wake=wake_word, last_wake_time=self.surf_context.wake_time)
        self._session_record("wake_received", wake_word=wake_word, session_id=self._session_id)
        self.get_logger().info(f'[WAKE] word="{wake_word}" session={self._session_id}')
        self.get_logger().info("on_wake no longer establishes conversation_session_id")
        self._open_wake_listen_window()
        self._maybe_play_wake_ack(wake_word)
        self._wake_ack_guard_until = time.monotonic() + max(0.0, CONFIG.wake_ack_guard_sec)
        self.get_logger().info(
            f"wake_ack guard armed until={self._wake_ack_guard_until:.3f} sec={CONFIG.wake_ack_guard_sec:.2f}"
        )

    def _interrupt_active_reply_for_wake(self, session_id: str) -> bool:
        if not self._interrupt_control.playback_active():
            return False

        command = self._interrupt_control.begin(session_id=session_id)
        generation = int(command["generation"])
        errors: list[str] = []
        try:
            from robot_relay.robot_relay_client import RobotRelayClient

            relay = RobotRelayClient(
                CONFIG.robot_relay_host,
                CONFIG.robot_relay_port,
                timeout_sec=CONFIG.robot_relay_timeout_sec,
            )
            stop_audio = relay.stop_audio("tts", generation=generation)
            if int(stop_audio.get("ret", -1)) != 0:
                errors.append(f"stop_audio ret={stop_audio.get('ret', 'missing')}")
            release_arm = relay.release_arm(generation=generation)
            if int(release_arm.get("ret", -1)) != 0:
                errors.append(f"release_arm ret={release_arm.get('ret', 'missing')}")
        except Exception as exc:
            errors.append(str(exc))

        try:
            self._interrupt_control.clear_playback_guard(command, kind="wake_interrupt")
        except Exception as exc:
            errors.append(f"clear_guard: {exc}")

        self._session_record(
            "wake_interrupt",
            session_id=session_id or self._session_id,
            generation=generation,
            errors=errors,
        )
        if errors:
            self.get_logger().warn(f"Wake interrupt completed with warnings: {errors}")
        else:
            self.get_logger().info("Wake word interrupted active reply; acknowledging new wake.")
        return True

    def _poll_session_command(self) -> None:
        command = self._interrupt_control.read_session_command()
        request_id = str(command.get("request_id", ""))
        if not request_id or request_id == self._last_session_command_request_id:
            return
        self._last_session_command_request_id = request_id
        if command.get("command") != "end_session":
            return

        session_id = str(command.get("session_id", "")).strip()
        request_session_id = (
            self._conversation_session_id
            or self._session_id
            or session_id
            or self._fallback_session_id()
        )
        self._session_record(
            "manual_session_end_received",
            request_id=request_id,
            generation=command.get("generation", 0),
            session_id=request_session_id,
        )
        self._handle_terminate_command(
            request_session_id,
            str(command.get("user_text", "")),
        )

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
            self.get_logger().info(f"[SPEAKER] label={speaker} score={score:.3f}")

    def on_audio_msg(self, msg: String) -> None:
        received_at = time.time()
        turn_generation = self._interrupt_control.current_generation()
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
            was_waiting_for_wake_command = self._wake_listen_waiting()
            if session_id:
                self._attach_session(session_id)
            self._close_wake_listen_window("empty_asr")
            self._set_wake_light_blue()
            if was_waiting_for_wake_command:
                self._play_standby_ack(session_id or self._session_id or self._fallback_session_id(), "wake_no_command")
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
            was_waiting_for_wake_command = self._wake_listen_waiting()
            self.get_logger().warn(f"Ignoring ASR text: reason={ignore_reason}, text={user_text}")
            self._update_status(
                last_ignored_asr=user_text,
                last_ignored_asr_reason=ignore_reason,
                last_error=f"ignored_asr:{ignore_reason}",
                updated_at=time.time(),
            )
            self._close_wake_listen_window(f"ignored_asr:{ignore_reason}")
            self._set_wake_light_blue()
            if was_waiting_for_wake_command:
                self._play_standby_ack(self._session_id or session_id or self._fallback_session_id(), "wake_no_command")
            return

        first_turn_guard_reason = self._first_turn_wake_ack_guard_reason(user_text)
        if first_turn_guard_reason:
            self.get_logger().info(
                f"wake_ack guard active; ignoring ASR text={user_text} reason={first_turn_guard_reason}"
            )
            self._update_status(
                last_ignored_asr=user_text,
                last_ignored_asr_reason=f"wake_ack_guard:{first_turn_guard_reason}",
                updated_at=time.time(),
            )
            self._session_record(
                "wake_ack_guard_ignored",
                text=user_text,
                reason=first_turn_guard_reason,
                session_id=self._session_id,
            )
            return

        if not self.force_always_listen:
            early_command_text = self.strip_wake_word(user_text)
            early_terminate_text = early_command_text if early_command_text is not None else user_text
            if self._is_terminate_command(user_text) or self._is_terminate_command(early_terminate_text):
                request_session_id = (
                    self._conversation_session_id
                    or self._session_id
                    or session_id
                    or self._fallback_session_id()
                )
                self.get_logger().info(
                    f"terminate command matched before self-speech guard raw={user_text} "
                    f"command_text={early_terminate_text} "
                    f"normalized={self._normalize_command_text(early_terminate_text)}"
                )
                self._handle_terminate_command(request_session_id, early_terminate_text)
                return

        self_speech, self_speech_reason = self._self_speech_asr_match(user_text)
        if self_speech:
            was_waiting_for_wake_command = self._wake_listen_waiting()
            followup_active = self._is_conversation_followup_session(session_id)
            self.get_logger().info(f"ignored self-speech ASR reason={self_speech_reason} text={user_text}")
            self._update_status(
                last_ignored_asr=user_text,
                last_ignored_asr_reason=f"self_speech:{self_speech_reason}",
                updated_at=time.time(),
            )
            self._session_record(
                "self_speech_asr_ignored",
                text=user_text,
                reason=self_speech_reason,
                session_id=self._session_id,
            )
            if was_waiting_for_wake_command and not followup_active:
                self._close_wake_listen_window("self_speech_asr")
                self._set_wake_light_blue()
                self._play_standby_ack(self._session_id or session_id or self._fallback_session_id(), "wake_no_command")
            return

        self.get_logger().info(
            "[ASR] "
            + (f"speaker={self.surf_context.speaker} " if self.surf_context.speaker else "")
            + f'text="{user_text}"'
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

        followup_turn = False
        if not self.force_always_listen:
            command_text = self.strip_wake_word(user_text)
            terminate_text = command_text if command_text is not None else user_text
            skill_text = terminate_text if command_text is not None else user_text
            skill_context_allowed = (
                command_text is not None
                or self._is_conversation_followup_session(session_id)
                or self._wake_listen_waiting()
            )
            if skill_context_allowed:
                skill = self._detect_robot_skill_command(skill_text)
                if skill:
                    request_session_id = (
                        self._conversation_session_id
                        or self._session_id
                        or session_id
                        or self._fallback_session_id()
                    )
                    self._handle_robot_skill_command(skill, request_session_id)
                    return
            if command_text is None:
                if self._is_conversation_followup_session(session_id):
                    followup_turn = True
                    command_text = user_text.strip()
                else:
                    if CONFIG.first_turn_strict_gate_enable and not self._conversation_session_id:
                        invalid, reason = self._is_invalid_first_turn_command(user_text)
                        normalized = self._normalize_first_turn_text(user_text)
                        if invalid:
                            self.get_logger().info(
                                f"ignored invalid first-turn command text={user_text} normalized={normalized} "
                                f"reason={reason} min_chars={CONFIG.first_turn_min_chars} "
                                f"require_intent={CONFIG.first_turn_require_intent}"
                            )
                            self._update_status(
                                last_ignored_asr=user_text,
                                last_ignored_asr_reason=f"first_turn:{reason}",
                                updated_at=time.time(),
                            )
                            self._session_record(
                                "first_turn_command_ignored",
                                text=user_text,
                                normalized=normalized,
                                reason=reason,
                                session_id=session_id or self._session_id or "default",
                            )
                            return
                        valid_reason = self._first_turn_valid_reason(user_text)
                        self.get_logger().info(
                            f"valid first-turn command text={user_text} normalized={normalized} reason={valid_reason}"
                        )
                    if self._wake_listen_waiting():
                        self._consume_wake_listen_window()
                    else:
                        self.get_logger().info(
                            "wake listen window inactive; accepting first-turn ASR text "
                            "after noise/self-speech filters."
                        )
                    command_text = user_text.strip()
            elif not command_text:
                self._open_wake_listen_window()
                self.get_logger().info(
                    "Second LLM wake filter matched. Waiting for the next ASR command event."
                )
                return
            user_text = command_text
        else:
            skill = self._detect_robot_skill_command(user_text)
            if skill:
                request_session_id = self._conversation_session_id or self._session_id or session_id or self._fallback_session_id()
                self._handle_robot_skill_command(skill, request_session_id)
                return

        llm_text = self._build_llm_text(user_text)
        if followup_turn and self._conversation_session_id:
            request_session_id = self._conversation_session_id
        else:
            request_session_id = self._conversation_session_id or self._session_id or session_id or self._fallback_session_id()
        if self._is_terminate_command(user_text):
            self.get_logger().info(
                f"terminate command matched raw={user_text} command_text={user_text} "
                f"normalized={self._normalize_command_text(user_text)}"
            )
            self._handle_terminate_command(request_session_id, user_text)
            return
        if not self._conversation_session_id:
            self._conversation_session_id = request_session_id
            self.get_logger().info(
                f"conversation_session_id established after valid user request session_id={request_session_id}"
            )
        if self._interrupt_control.generation_changed(turn_generation):
            self._discard_interrupted_turn(request_session_id, "before_llm")
            return
        llm_started_at = time.time()
        self._set_wake_light_green()
        self._session_record("thinking", text=user_text, session_id=request_session_id)
        self._run_thinking_action()
        skip_thinking_ack = self._should_skip_thinking_ack_for_action(user_text)
        if skip_thinking_ack:
            pass
        else:
            queued_thinking_ack = self._maybe_play_thinking_ack(request_session_id)
            if queued_thinking_ack and CONFIG.thinking_ack_play_gap_sec > 0:
                self.get_logger().info(
                    f"thinking_ack play gap sleep={CONFIG.thinking_ack_play_gap_sec:.2f}s"
                )
                time.sleep(CONFIG.thinking_ack_play_gap_sec)
        llm_response = self._request_llm(llm_text, session_id=request_session_id, user_text=user_text)
        llm_finished_at = time.time()
        if self._interrupt_control.generation_changed(turn_generation):
            self._discard_interrupted_turn(request_session_id, "after_llm")
            return
        reply = str(llm_response.get("reply", "")).strip()
        action_payload = llm_response.get("action", {})
        if not reply:
            error = str(llm_response.get("error", "")).strip() or "empty_reply"
            self._update_status(last_error="llm_request_failed", updated_at=time.time())
            self._session_record(
                "llm_failed",
                error=error,
                timeout_sec=CONFIG.request_timeout_sec,
                session_id=request_session_id,
            )
            self._set_wake_light_blue()
            self._close_session("session_end")
            return

        self.get_logger().info(f'[LLM] reply="{reply}"')
        timing = llm_response.get("timing", {})
        self._update_status(
            last_reply=reply,
            last_reply_time=llm_finished_at,
            latency={
                **self.status.get("latency", {}),
                "llm_ms": self._elapsed_ms(llm_started_at, llm_finished_at),
                "wake_to_reply_ms": self._elapsed_ms(self.surf_context.wake_time, llm_finished_at),
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
            reply_tts_text = self._build_reply_tts_text(reply, user_text=user_text)
            tts_ok = self._prepare_tts_wav(
                "reply",
                reply_tts_text,
                session_id=request_session_id,
                generation=turn_generation,
            )
        except Exception as exc:
            self.get_logger().warn(f"Reply TTS request failed: {exc}")
            tts_ok = False
        if not tts_ok:
            self._update_status(last_error="tts_wav_failed", updated_at=time.time())
            self._session_record("tts_failed", session_id=request_session_id)
            self._set_wake_light_blue()
            self._close_session("session_end")
            return
        if self._interrupt_control.generation_changed(turn_generation):
            self._discard_interrupted_turn(request_session_id, "after_tts")
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
            args=(reply, user_text, action_payload, turn_generation),
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
        timeout_sec = max(0.1, CONFIG.wake_listen_sec)
        with self._wake_state_lock:
            self.awaiting_command_after_wake = True
            self._wake_listen_until = time.monotonic() + timeout_sec
            self._wake_listen_generation += 1
            self._wake_command_started = False
            generation = self._wake_listen_generation
            wake_listen_until = self._wake_listen_until
            session_id = self._session_id

        self._update_status(
            wake_listen_active=True,
            wake_listen_until=time.time() + timeout_sec,
            wake_listen_sec=timeout_sec,
        )
        self._session_record(
            "wake_listen_open",
            session_id=session_id,
            generation=generation,
            timeout_sec=timeout_sec,
        )
        self.get_logger().info(
            f"wake listen window opened session_id={session_id} until={wake_listen_until:.3f} sec={timeout_sec:.2f}"
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

    def _poll_wake_listen_timeout(self) -> None:
        with self._wake_state_lock:
            if not self.awaiting_command_after_wake:
                return
            if self._wake_listen_until <= 0.0:
                return
            if time.monotonic() < self._wake_listen_until:
                return
        self._expire_wake_listen_window("timeout")

    def _expire_wake_listen_window(self, reason: str = "timeout") -> None:
        session_id = ""
        with self._wake_state_lock:
            if not self.awaiting_command_after_wake:
                return
            if self._conversation_session_id:
                return
            session_id = self._session_id or self._fallback_session_id()
            self.awaiting_command_after_wake = False
            self._wake_listen_until = 0.0
            self._wake_command_started = False

        self._update_status(
            wake_listen_active=False,
            last_wake_listen_closed_reason=reason,
            last_wake_listen_closed_time=time.time(),
        )
        self._session_record("wake_listen_closed", reason=reason, session_id=session_id)
        self.get_logger().info(f"wake listen window timeout session_id={session_id}")
        self.get_logger().info(f"wake listen window closed reason={reason}")
        self._set_wake_light_blue()
        if reason == "timeout":
            self._play_standby_ack(session_id, "wake_listen_timeout")

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

    def _wake_listen_waiting(self) -> bool:
        with self._wake_state_lock:
            return bool(self.awaiting_command_after_wake or self._wake_listen_until > 0)

    def _open_followup_window(self, session_id: str, reason: str) -> None:
        if not CONFIG.followup_enable or CONFIG.followup_timeout_sec <= 0:
            return
        with self._wake_state_lock:
            self._conversation_session_id = session_id
            self._followup_until = time.monotonic() + CONFIG.followup_timeout_sec
            self._followup_generation += 1
            generation = self._followup_generation

        self._update_status(
            followup_active=True,
            followup_session_id=session_id,
            followup_timeout_sec=CONFIG.followup_timeout_sec,
            followup_until=time.time() + CONFIG.followup_timeout_sec,
            followup_reason=reason,
        )
        self._session_record(
            "followup_open",
            session_id=session_id,
            timeout_sec=CONFIG.followup_timeout_sec,
            reason=reason,
        )
        threading.Thread(target=self._expire_followup_window, args=(generation,), daemon=True).start()

    def _followup_active(self) -> bool:
        if not CONFIG.followup_enable:
            return False
        with self._wake_state_lock:
            if not self._conversation_session_id or not self._followup_until:
                return False
            active = time.monotonic() <= self._followup_until
        if active:
            return True
        self._close_followup_window("timeout")
        return False

    def _is_conversation_followup_session(self, session_id: str) -> bool:
        if not CONFIG.followup_enable:
            return False
        session_id = (session_id or "").strip()
        if not session_id:
            return False
        with self._wake_state_lock:
            return bool(self._conversation_session_id) and session_id == self._conversation_session_id

    def _expire_followup_window(self, generation: int) -> None:
        timeout_sec = max(0.0, CONFIG.followup_timeout_sec)
        time.sleep(timeout_sec)
        with self._wake_state_lock:
            if generation != self._followup_generation:
                return
            if not self._conversation_session_id or time.monotonic() <= self._followup_until:
                return
        self._close_followup_window("timeout")
        self._set_wake_light_blue()

    def _close_followup_window(self, reason: str) -> None:
        with self._wake_state_lock:
            if not self._conversation_session_id and not self._followup_until:
                return
            session_id = self._conversation_session_id
            self._conversation_session_id = ""
            self._followup_until = 0.0
            self._followup_generation += 1

        self._update_status(
            followup_active=False,
            followup_session_id=session_id,
            last_followup_closed_reason=reason,
            last_followup_closed_time=time.time(),
        )
        self._session_record("followup_closed", reason=reason, session_id=session_id or self._session_id)

    def _normalize_command_text(self, text: str) -> str:
        return normalize_command_text(text)

    def _is_terminate_command(self, text: str) -> bool:
        if not CONFIG.terminate_command_enable:
            return False
        return matches_command(text, CONFIG.terminate_commands)

    def _handle_terminate_command(self, session_id: str, user_text: str = "") -> None:
        self.get_logger().info("terminate command received; closing interaction")
        with self._wake_state_lock:
            self._conversation_session_id = ""
            self._followup_until = 0.0
            self._followup_generation += 1
            self.awaiting_command_after_wake = False
            self._wake_listen_until = 0.0
            self._wake_command_started = False

        self._update_status(
            followup_active=False,
            followup_session_id="",
            wake_listen_active=False,
            last_followup_closed_reason="terminate_command",
            last_wake_listen_closed_reason="terminate_command",
            last_terminate_command_time=time.time(),
        )
        self._session_record("terminate_command", session_id=session_id)
        self._write_followup_control_close(session_id, "terminate_command")
        self._set_wake_light_blue()

        ack_text = select_terminate_ack_text(
            user_text,
            CONFIG.terminate_ack_text,
            CONFIG.terminate_ack_text_en,
        )
        if not ack_text:
            return
        try:
            tts_ready = self._prepare_tts_wav("system_ack", ack_text, session_id=session_id)
            if tts_ready:
                self._queue_terminate_wave(ack_text, session_id)
        except Exception as exc:
            self.get_logger().warn(f"Terminate ack TTS request failed: {exc}")
            self._session_record("terminate_ack_failed", reason=str(exc), session_id=session_id)

    def _write_followup_control_close(self, session_id: str, reason: str) -> None:
        try:
            CONFIG.followup_control_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "command": "close",
                "session_id": session_id,
                "reason": reason,
                "updated_at": time.time(),
            }
            CONFIG.followup_control_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            self.get_logger().info(f"followup_control close written: reason={reason}")
        except Exception as exc:
            self.get_logger().warn(f"Follow-up control close write failed: {exc}")

    def _poll_standby_ack_event(self) -> None:
        path = CONFIG.standby_ack_event_path
        if not path.exists():
            return
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            self.get_logger().warn(f"Standby ack event stat failed: {exc}")
            return
        if mtime == self._standby_ack_event_mtime:
            return
        self._standby_ack_event_mtime = mtime

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.get_logger().warn(f"Standby ack event parse failed: {exc}")
            return

        if str(payload.get("event", "")).strip() != "standby_ack":
            return
        try:
            updated_at = float(payload.get("updated_at", 0.0))
        except (TypeError, ValueError):
            updated_at = 0.0
        if updated_at <= self._standby_ack_event_updated_at:
            return
        self._standby_ack_event_updated_at = updated_at

        reason = str(payload.get("reason", "")).strip() or "unknown"
        if reason != "followup_timeout":
            self.get_logger().info(f"Ignoring standby ack event reason={reason}")
            return
        session_id = str(payload.get("session_id", "")).strip() or self._fallback_session_id()
        self._clear_conversation_after_real_followup_timeout(session_id)
        self._play_standby_ack(session_id, reason)

    def _clear_conversation_after_real_followup_timeout(self, session_id: str) -> None:
        with self._wake_state_lock:
            if session_id and self._conversation_session_id and session_id != self._conversation_session_id:
                return
            self._conversation_session_id = ""
            self._followup_until = 0.0
            self._followup_generation += 1
            self.awaiting_command_after_wake = False
            self._wake_listen_until = 0.0
            self._wake_command_started = False

        self._update_status(
            followup_active=False,
            followup_session_id=session_id,
            wake_listen_active=False,
            last_followup_closed_reason="followup_timeout",
            last_followup_closed_time=time.time(),
        )
        self._session_record("followup_closed", reason="followup_timeout", session_id=session_id or self._session_id)
        self.get_logger().info(
            f"conversation_session_id cleared after real followup timeout session_id={session_id}"
        )

    def _play_standby_ack(self, session_id: str, reason: str) -> None:
        if not CONFIG.standby_ack_enable:
            self.get_logger().info(f"[STANDBY] skipped reason={reason} enabled=False")
            self._session_record("standby_ack_skipped", reason=reason, enabled=False, session_id=session_id)
            return
        ack_text = CONFIG.standby_ack_text.strip()
        if not ack_text:
            self.get_logger().info(f"[STANDBY] skipped reason={reason} empty_text=True")
            self._session_record("standby_ack_skipped", reason=reason, empty_text=True, session_id=session_id)
            return
        try:
            tts_ok = self._prepare_tts_wav("system_ack", ack_text, session_id=session_id)
        except Exception as exc:
            self.get_logger().warn(f"Standby ack TTS request failed: {exc}")
            self._session_record("standby_ack_failed", reason=reason, error=str(exc), session_id=session_id)
            return
        if not tts_ok:
            self._session_record("standby_ack_failed", reason=reason, error="wav_failed", session_id=session_id)
            return
        self.get_logger().info(f"standby ack queued reason={reason}")
        self._session_record("standby_ack_ready", text=ack_text, reason=reason, session_id=session_id)

    def _normalize_asr_text(self, text: str) -> str:
        normalized = (text or "").lower()
        return re.sub(r"[\s，。！？、,.!?;:：；'\"“”‘’\-()（）\[\]{}]", "", normalized)

    def _normalize_first_turn_text(self, text: str) -> str:
        return self._normalize_asr_text(text)

    def _has_first_turn_intent(self, text: str) -> bool:
        normalized = self._normalize_first_turn_text(text)
        keywords = (
            "介绍",
            "讲",
            "说",
            "告诉",
            "帮我",
            "带我",
            "了解",
            "哪里",
            "在哪",
            "什么",
            "哪些",
            "谁",
            "你是",
            "你叫",
            "名字",
            "身份",
            "自我介绍",
            "多少",
            "怎么",
            "为什么",
            "能不能",
            "可以不",
            "专业",
            "学校",
            "校区",
            "学院",
            "课程",
            "申请",
            "学费",
            "宿舍",
            "食堂",
            "图书馆",
            "西交",
            "西郊",
            "西浦",
            "利物浦",
            "大学",
        )
        return any(self._normalize_first_turn_text(keyword) in normalized for keyword in keywords)

    def _looks_like_first_turn_noise(self, text: str) -> bool:
        normalized = self._normalize_first_turn_text(text)
        if not normalized:
            return False
        if self._is_terminate_command(normalized):
            return False
        if self._detect_robot_skill_command(normalized):
            return False
        action_like, _, _ = self._looks_like_action_request(normalized)
        if action_like:
            return False
        if self._has_first_turn_intent(normalized):
            return False

        noisy_prefixes = (
            "我在",
            "存在",
            "准在",
            "不意",
            "不意思",
            "嗯",
            "啊",
            "呃",
            "哦",
            "好",
            "好的",
            "你好",
            "小浦",
        )
        if normalized.startswith(noisy_prefixes):
            return True

        if len(normalized) <= 8:
            return True

        if len(normalized) <= 10:
            unique_ratio = len(set(normalized)) / max(1, len(normalized))
            if unique_ratio <= 0.55:
                return True

        return False

    def _is_invalid_first_turn_command(self, text: str) -> tuple[bool, str]:
        normalized = self._normalize_first_turn_text(text)
        if not normalized:
            return True, "empty"
        if self._is_terminate_command(text):
            return False, "terminate_command"
        if self._detect_robot_skill_command(text):
            return False, "robot_skill"
        action_like, _, _ = self._looks_like_action_request(text)
        if action_like:
            return False, "action_intent"

        noise_texts = {self._normalize_first_turn_text(item) for item in CONFIG.first_turn_noise_texts}
        if normalized in noise_texts:
            return True, "noise_text"

        if len(normalized) < max(1, CONFIG.first_turn_min_chars):
            return True, "too_short"

        if self._looks_like_first_turn_noise(normalized):
            return True, "noise_like"

        if CONFIG.first_turn_require_intent and not self._has_first_turn_intent(text):
            return True, "no_intent"

        return False, ""

    def _first_turn_valid_reason(self, text: str) -> str:
        if self._is_terminate_command(text):
            return "terminate_command"
        skill = self._detect_robot_skill_command(text)
        if skill:
            return f"robot_skill:{skill.get('command', '')}"
        action_like, _, keyword = self._looks_like_action_request(text)
        if action_like:
            return f"action_intent:{keyword}"
        if self._has_first_turn_intent(text):
            return "question_intent"
        return "accepted"

    def _first_turn_wake_ack_guard_reason(self, user_text: str) -> str:
        if not self._wake_listen_waiting():
            return ""
        normalized = self._normalize_asr_text(user_text)
        if not normalized:
            return ""

        guard_reason = ""
        try:
            guard = self._read_tts_guard()
        except Exception:
            guard = {}
        now = time.time()
        try:
            guard_until = float(guard.get("guard_until", 0.0))
        except (TypeError, ValueError):
            guard_until = 0.0
        try:
            guard_updated_at = float(guard.get("updated_at", 0.0))
        except (TypeError, ValueError):
            guard_updated_at = 0.0
        guard_kind = str(guard.get("kind", "")).strip()
        wake_ack_guard_active = (
            guard_kind == "wake_ack"
            and (bool(guard.get("active", False)) or now < guard_until + max(0.0, CONFIG.wake_ack_guard_sec))
        )
        if not wake_ack_guard_active:
            return ""

        blocked = {
            "我在",
            "我",
            "在",
            "嗯",
            "啊",
            "呃",
            "哦",
            "好",
            "好的",
            "你好",
            "小浦",
            "你好小浦",
        }
        if normalized in {self._normalize_asr_text(item) for item in blocked}:
            return "filler"

        wake_word_like = {
            self._normalize_asr_text(item)
            for item in CONFIG.wake_words
        }
        if normalized in wake_word_like and (now - guard_updated_at < max(0.0, CONFIG.wake_ack_guard_sec) + 1.0):
            return "wake_word_echo"

        if len(normalized) <= 2 and normalized in {"我", "在", "好", "嗯", "啊", "哦"}:
            return "short_filler"

        return ""

    def _read_tts_guard(self) -> dict[str, Any]:
        if not CONFIG.tts_guard_enable or not CONFIG.tts_guard_path.exists():
            return {}
        try:
            payload = json.loads(CONFIG.tts_guard_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.get_logger().warn(f"TTS guard read failed: {exc}")
            return {}
        return payload if isinstance(payload, dict) else {}

    def _self_speech_asr_match(self, user_text: str) -> tuple[bool, str]:
        if not CONFIG.tts_guard_enable:
            return False, ""
        normalized_asr = self._normalize_asr_text(user_text)
        if not normalized_asr:
            return False, ""

        guard = self._read_tts_guard()
        now = time.time()
        try:
            guard_until = float(guard.get("guard_until", 0.0))
        except (TypeError, ValueError):
            guard_until = 0.0
        try:
            guard_updated_at = float(guard.get("updated_at", 0.0))
        except (TypeError, ValueError):
            guard_updated_at = 0.0
        high_risk_window = (
            bool(guard.get("active", False))
            or now < guard_until + 3.0
            or (guard_updated_at > 0.0 and now - guard_updated_at < 10.0)
        )
        guard_kind = str(guard.get("kind", "")).strip()
        guard_text = str(guard.get("text", ""))
        normalized_tts = self._normalize_asr_text(guard_text)

        fixed_phrases = (
            "我在",
            "我",
            "在",
            "嗯",
            "啊",
            "呃",
            "哦",
            "好",
            "好的",
            "你好",
            "小浦",
            "你好小浦",
            "小浦思考中",
            "还有什么想问的吗",
            "anything else to ask",
            "待机",
            "好的已关闭交互",
        )
        for phrase in fixed_phrases:
            normalized_phrase = self._normalize_asr_text(phrase)
            if normalized_asr == normalized_phrase:
                return True, f"fixed_phrase:{phrase}"

        followup_prompts = (
            CONFIG.followup_prompt_text,
            CONFIG.followup_prompt_text_zh,
            CONFIG.followup_prompt_text_en,
        )
        for prompt_text in followup_prompts:
            followup_prompt = self._normalize_asr_text(prompt_text)
            if followup_prompt and normalized_asr == followup_prompt:
                return True, "reply_followup_prompt_echo"

        if not normalized_tts:
            return False, ""
        ratio = difflib.SequenceMatcher(None, normalized_asr, normalized_tts).ratio()
        if high_risk_window and ratio >= CONFIG.self_speech_similarity_threshold:
            return True, f"similar_to_tts:{guard_kind}:ratio={ratio:.2f}"
        return False, ""

    def _is_self_speech_asr(self, user_text: str) -> bool:
        matched, _ = self._self_speech_asr_match(user_text)
        return matched

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

    def _build_llm_text(self, user_text: str) -> str:
        if CONFIG.reply_backend == "rag":
            return user_text
        if not CONFIG.include_speaker_context or not self.surf_context.speaker:
            return user_text

        return (
            f"系统上下文：当前说话人是{self.surf_context.speaker}。"
            "除非用户询问身份或上下文，否则不要在回复中复述这句系统上下文。"
            f"\n用户说：{user_text}"
        )

    @staticmethod
    def _looks_english(text: str) -> bool:
        return bool(re.search(r"[A-Za-z]", text or "")) and not bool(re.search(r"[\u4e00-\u9fff]", text or ""))

    def _followup_prompt_for_text(self, reply: str, user_text: str = "") -> str:
        if self._looks_english(user_text) or self._looks_english(reply):
            return CONFIG.followup_prompt_text_en.strip()
        return CONFIG.followup_prompt_text_zh.strip()

    def _build_reply_tts_text(self, reply: str, user_text: str = "") -> str:
        if not CONFIG.followup_enable or not CONFIG.followup_prompt_enable:
            return reply
        prompt = self._followup_prompt_for_text(reply, user_text)
        if not prompt:
            return reply
        return f"{reply} {prompt}".strip()

    def _normalize_robot_skill_text(self, text: str) -> str:
        normalized = (text or "").lower()
        return re.sub(r"[\s，。！？、,.!?;:：；'\"“”‘’\-()（）\[\]{}]", "", normalized)

    def _is_direct_robot_stop_request(self, text: str, keyword: str) -> bool:
        normalized = self._normalize_robot_skill_text(text)
        target = self._normalize_robot_skill_text(keyword)
        if normalized == target:
            return True

        prefixes = ("小浦", "请", "你", "麻烦", "现在", "马上")
        suffixes = ("一下", "吧", "好吗", "可以吗")
        candidate = normalized
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if candidate.startswith(prefix):
                    candidate = candidate[len(prefix):]
                    changed = True
                    break
            for suffix in suffixes:
                if candidate.endswith(suffix):
                    candidate = candidate[:-len(suffix)]
                    changed = True
                    break
        return candidate == target

    def _detect_robot_skill_command(self, text: str) -> dict[str, str] | None:
        if not CONFIG.robot_skill_enable:
            return None
        normalized = self._normalize_robot_skill_text(text)
        if not normalized:
            return None

        command_keywords: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("stop", ("停下", "停止", "别动", "不要动", "原地站好")),
            ("forward_step", ("向前一步", "往前一步", "前进一步", "往前走一步", "向前走一步")),
            ("backward_step", ("后退一步", "往后退一步", "向后退一步", "退后一步")),
            ("turn_left", ("左转一点", "向左转", "往左转", "左转一下")),
            ("turn_right", ("右转一点", "向右转", "往右转", "右转一下")),
            ("squat", ("下蹲", "蹲下", "蹲一下")),
            ("lie_down", ("躺下", "趴下", "倒下")),
            ("stand_up", ("站起来", "起立", "站好")),
            ("sing", ("唱歌", "唱首歌", "唱一首歌", "给我唱歌")),
        )
        for command, keywords in command_keywords:
            for keyword in keywords:
                normalized_keyword = self._normalize_robot_skill_text(keyword)
                if normalized_keyword and normalized_keyword in normalized:
                    if command == "stop" and not self._is_direct_robot_stop_request(text, keyword):
                        continue
                    return {
                        "command": command,
                        "text": text,
                        "normalized": normalized,
                        "matched": keyword,
                    }
        return None

    def _queue_terminate_wave(self, ack_text: str, session_id: str) -> None:
        if not CONFIG.action_enable or not CONFIG.action_execute:
            self._session_record(
                "terminate_wave_skipped",
                reason="action_disabled",
                session_id=session_id,
            )
            return
        if not self._action_lock.acquire(blocking=False):
            self._session_record(
                "terminate_wave_skipped",
                reason="action_busy",
                session_id=session_id,
            )
            return
        threading.Thread(
            target=self._run_terminate_wave_locked,
            args=(ack_text, session_id),
            daemon=True,
        ).start()

    def _run_terminate_wave_locked(self, ack_text: str, session_id: str) -> None:
        started_at = time.time()
        classification = {
            "text": ack_text,
            "label": "高位挥手",
            "official_name": "high wave",
            "action_id": 26,
            "score": 1.0,
            "backend": "terminate_ack",
            "should_execute": True,
            "reason": "conversation termination acknowledgement",
        }
        try:
            execution = self._execute_classified_action(classification)
            self._log_action_result(classification, execution, started_at, ack_text)
            self._session_record(
                "terminate_wave",
                executed=execution.get("executed", False),
                reason=execution.get("reason", ""),
                session_id=session_id,
            )
        finally:
            self._action_lock.release()

    def _robot_skill_ack_text(self, command: str) -> str:
        if command == "stop":
            return "已停止"
        return "好的"

    def _handle_robot_skill_command(self, skill: dict[str, str], session_id: str) -> None:
        command_name = skill.get("command", "").strip()
        normalized = skill.get("normalized", "")
        text = skill.get("text", "")
        matched = skill.get("matched", "")
        if not command_name:
            return

        self.get_logger().info(
            f"robot skill command matched text={text} normalized={normalized} "
            f"command={command_name} matched={matched}"
        )
        self._session_record(
            "robot_skill_matched",
            text=text,
            normalized=normalized,
            command=command_name,
            matched=matched,
            session_id=session_id,
        )
        if self._wake_listen_waiting():
            self._consume_wake_listen_window()
        if not self._conversation_session_id:
            self._conversation_session_id = session_id
            self.get_logger().info(
                f"conversation_session_id established after robot skill command session_id={session_id}"
            )
        self._set_wake_light_blue()

        if command_name == "sing":
            song_ok = self._queue_robot_skill_song(session_id)
            self._update_status(
                last_robot_skill_command=command_name,
                last_robot_skill_text=text,
                last_robot_skill_ok=song_ok,
                last_robot_skill_time=time.time(),
            )
            return

        runner_ok = self._run_robot_skill_runner(command_name, session_id)
        ack_text = self._robot_skill_ack_text(command_name)
        if CONFIG.robot_skill_ack_enable and ack_text:
            try:
                tts_ok = self._prepare_tts_wav("reply", ack_text, session_id=session_id)
            except Exception as exc:
                self.get_logger().warn(f"Robot skill ack TTS request failed: {exc}")
                tts_ok = False
            if not tts_ok:
                self._session_record(
                    "robot_skill_ack_failed",
                    command=command_name,
                    session_id=session_id,
                )

        self._update_status(
            last_robot_skill_command=command_name,
            last_robot_skill_text=text,
            last_robot_skill_ok=runner_ok,
            last_robot_skill_time=time.time(),
        )

    def _queue_robot_skill_song(self, session_id: str) -> bool:
        song_path = CONFIG.robot_skill_song_file
        if song_path.exists() and song_path.is_file():
            if song_path.suffix.lower() != ".wav":
                self.get_logger().warn(
                    f"robot skill sing file must be wav for direct playback path={song_path}"
                )
            else:
                try:
                    with self._tts_lock:
                        CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)
                        CONFIG.tts_wav_path.parent.mkdir(parents=True, exist_ok=True)
                        self._write_tts_play_context(
                            "system_ack",
                            f"song:{song_path.name}",
                            session_id=session_id,
                        )
                        shutil.copyfile(song_path, CONFIG.tts_wav_path)
                    self.get_logger().info(f"robot skill song queued path={song_path}")
                    self._session_record(
                        "robot_skill_song_queued",
                        path=str(song_path),
                        session_id=session_id,
                    )
                    return True
                except Exception as exc:
                    self.get_logger().warn(f"robot skill song queue failed path={song_path} error={exc}")
                    self._session_record(
                        "robot_skill_song_failed",
                        path=str(song_path),
                        error=str(exc),
                        session_id=session_id,
                    )

        fallback_text = CONFIG.robot_skill_sing_fallback_text.strip()
        if not fallback_text:
            self.get_logger().warn(f"robot skill sing failed: song file missing path={song_path}")
            self._session_record(
                "robot_skill_song_failed",
                path=str(song_path),
                reason="missing_song_file_and_empty_fallback",
                session_id=session_id,
            )
            return False

        try:
            tts_ok = self._prepare_tts_wav("system_ack", fallback_text, session_id=session_id)
        except Exception as exc:
            self.get_logger().warn(f"robot skill sing fallback TTS failed: {exc}")
            tts_ok = False
        if tts_ok:
            self.get_logger().info("robot skill sing fallback TTS queued")
            self._session_record(
                "robot_skill_song_fallback_queued",
                text=fallback_text,
                session_id=session_id,
            )
        return tts_ok

    def _run_robot_skill_runner(self, command_name: str, session_id: str) -> bool:
        runner = CONFIG.robot_skill_runner
        if not runner.exists():
            self.get_logger().warn(f"robot skill failed command={command_name} error=runner_not_found path={runner}")
            self._session_record(
                "robot_skill_failed",
                command=command_name,
                reason="runner_not_found",
                runner=str(runner),
                session_id=session_id,
            )
            return False

        cmd = [
            sys.executable,
            str(runner),
            "--command",
            command_name,
            "--network_interface",
            CONFIG.unitree_network_interface,
            "--execute",
            "1" if CONFIG.robot_skill_execute else "0",
        ]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except Exception as exc:
            self.get_logger().warn(f"robot skill failed command={command_name} error={exc}")
            self._session_record(
                "robot_skill_failed",
                command=command_name,
                error=str(exc),
                session_id=session_id,
            )
            return False

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        for line in stdout.splitlines():
            self.get_logger().info(line)
        for line in stderr.splitlines():
            self.get_logger().warn(line)
        if result.returncode != 0:
            self.get_logger().warn(
                f"robot skill failed command={command_name} returncode={result.returncode}"
            )
            self._session_record(
                "robot_skill_failed",
                command=command_name,
                returncode=result.returncode,
                stdout=stdout,
                stderr=stderr,
                session_id=session_id,
            )
            return False

        self.get_logger().info(
            f"robot skill executed command={command_name} execute={CONFIG.robot_skill_execute}"
        )
        self._session_record(
            "robot_skill_executed",
            command=command_name,
            execute=CONFIG.robot_skill_execute,
            stdout=stdout,
            session_id=session_id,
        )
        return True

    def _normalize_action_intent_text(self, text: str) -> str:
        normalized = (text or "").lower()
        return re.sub(r"[\s，。！？、,.!?;:：；'\"“”‘’()（）\[\]{}]", "", normalized)

    def _looks_like_action_request(self, text: str) -> tuple[bool, str, str]:
        normalized = self._normalize_action_intent_text(text)
        keywords = (
            "挥手",
            "挥个手",
            "打招呼",
            "打个招呼",
            "招呼一下",
            "握手",
            "握个手",
            "鼓掌",
            "鼓个掌",
            "击掌",
            "比心",
            "比个心",
            "拥抱",
            "飞吻",
            "举手",
            "举个手",
            "抬手",
            "摆手",
            "摆个手",
            "跳舞",
            "跳个舞",
            "拒绝",
            "释放手臂",
            "放下手",
            "动作",
            "做个动作",
            "做一个动作",
            "来个动作",
            "表演一下",
            "欢迎一下",
            "示意一下",
            "xray",
            "x-ray",
            "x光",
        )
        for keyword in keywords:
            normalized_keyword = self._normalize_action_intent_text(keyword)
            if normalized_keyword and normalized_keyword in normalized:
                return True, normalized, keyword
        return False, normalized, ""

    def _should_skip_thinking_ack_for_action(self, user_text: str) -> bool:
        if not CONFIG.thinking_ack_skip_action_intent:
            return False
        matched, normalized, keyword = self._looks_like_action_request(user_text)
        if not matched:
            return False
        self.get_logger().info(
            f"thinking_ack skipped: action-like user request text={user_text} "
            f"normalized={normalized} matched={keyword}"
        )
        return True

    def _fallback_session_id(self) -> str:
        speaker = self.surf_context.speaker.strip() if self.surf_context.speaker else "default"
        return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", speaker) or "default"

    def _request_llm(self, text: str, session_id: str = "default", user_text: str = "") -> dict[str, Any]:
        try:
            response = HTTP_SESSION.get(
                CONFIG.llm_server_url,
                params={"text": text, "session_id": session_id, "user_text": user_text},
                timeout=CONFIG.request_timeout_sec,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            self.get_logger().error(f"LLM request failed: {exc}")
            return {"reply": "", "error": str(exc)}

        reply = str(result.get("reply", "")).strip()
        if not reply:
            self.get_logger().error("Empty reply from LLM")
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
        self._set_wake_light_color("green", 0, 255, 0, effect="blink")

    def _set_wake_light_blue(self) -> None:
        self._set_wake_light_color("blue", 0, 0, 255)

    def _write_tts_play_context(
        self,
        kind: str,
        text: str = "",
        session_id: str = "",
        generation: int | None = None,
    ) -> None:
        try:
            payload = {
                "kind": kind,
                "text": text,
                "session_id": session_id or self._session_id or "default",
                "generation": generation,
                "updated_at": time.time(),
            }
            CONFIG.tts_play_context_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            self.get_logger().warn(f"TTS play context write failed: {exc}")

    def _request_tts_mp3(self, text: str, output_path=None):
        response = HTTP_SESSION.get(
            self._llm_tts_url(),
            params={"text": text},
            timeout=CONFIG.request_timeout_sec,
        )
        response.raise_for_status()
        target_path = output_path or CONFIG.tts_mp3_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.{threading.get_ident()}.tmp")
        temp_path.write_bytes(response.content)
        os.replace(temp_path, target_path)
        return target_path

    def _temporary_tts_mp3_path(self):
        return CONFIG.runtime_dir / f".tts-{threading.get_ident()}-{time.time_ns()}.mp3"

    def _prepare_tts_wav(
        self,
        kind: str,
        text: str,
        session_id: str = "",
        generation: int | None = None,
    ) -> bool:
        with self._tts_lock:
            self._write_tts_play_context(kind, text, session_id=session_id, generation=generation)
            mp3_path = self._temporary_tts_mp3_path()
            try:
                self._request_tts_mp3(text, mp3_path)
                return self._convert_tts_to_wav(input_path=mp3_path)
            finally:
                mp3_path.unlink(missing_ok=True)

    def _discard_interrupted_turn(self, session_id: str, stage: str) -> None:
        self.get_logger().info(f"discarding stale turn after manual interrupt stage={stage}")
        self._session_record(
            "stale_turn_discarded",
            stage=stage,
            session_id=session_id,
        )

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

    def _maybe_play_thinking_ack(self, session_id: str) -> bool:
        if not CONFIG.thinking_ack_enable:
            return False
        ack_text = CONFIG.thinking_ack_text.strip()
        if not ack_text:
            return False
        return self._play_thinking_ack(ack_text, session_id)

    def _play_thinking_ack(self, ack_text: str, session_id: str) -> bool:
        started_at = time.time()
        try:
            tts_ok = self._prepare_tts_wav("thinking_ack", ack_text, session_id=session_id)
        except Exception as exc:
            self.get_logger().warn(f"Thinking ack TTS request failed: {exc}")
            self._session_record("thinking_ack_failed", text=ack_text, reason=str(exc), session_id=session_id)
            return False

        if not tts_ok:
            self._session_record("thinking_ack_failed", text=ack_text, reason="wav_failed", session_id=session_id)
            return False

        self.get_logger().info(f"Thinking ack played: {ack_text}")
        self._session_record(
            "thinking_ack_ready",
            text=ack_text,
            session_id=session_id,
            duration_ms=self._elapsed_ms(started_at, time.time()),
        )
        return True

    def _play_wake_ack(self, ack_text: str) -> None:
        started_at = time.time()
        try:
            with self._tts_lock:
                self._write_tts_play_context("wake_ack", ack_text)
                cache_path = self._wake_ack_cache_path(ack_text)
                if not self._wake_ack_cache_valid(cache_path):
                    if not self._build_wake_ack_cache(ack_text, cache_path):
                        self._update_status(last_error="wake_ack_wav_failed", updated_at=time.time())
                        return
                self._publish_cached_wake_ack(cache_path)
        except Exception as exc:
            self.get_logger().warn(f"Wake ack TTS request failed: {exc}")
            self._update_status(last_error="wake_ack_tts_failed", updated_at=time.time())
            return

        self._run_wake_ack_action()
        self.get_logger().info(f'[TTS] wake_ack text="{ack_text}"')
        self._update_status(
            last_wake_ack=ack_text,
            last_wake_ack_time=time.time(),
            latency={
                **self.status.get("latency", {}),
                "wake_ack_ms": self._elapsed_ms(started_at, time.time()),
            },
        )
        self._session_record("wake_ack_ready", text=ack_text, session_id=self._session_id)

    def _wake_ack_cache_path(self, ack_text: str):
        digest = hashlib.sha256(ack_text.encode("utf-8")).hexdigest()[:16]
        cache_dir = CONFIG.runtime_dir / "tts_cache"
        return cache_dir / f"wake_ack_{digest}.wav"

    def _publish_cached_wake_ack(self, cache_path) -> None:
        CONFIG.tts_wav_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = CONFIG.tts_wav_path.with_name(f".{CONFIG.tts_wav_path.name}.wake.tmp")
        shutil.copyfile(cache_path, temp_path)
        os.replace(temp_path, CONFIG.tts_wav_path)

    @staticmethod
    def _wake_ack_cache_valid(cache_path) -> bool:
        try:
            with wave.open(str(cache_path), "rb") as wav_file:
                return (
                    wav_file.getnchannels() == 1
                    and wav_file.getsampwidth() == 2
                    and wav_file.getframerate() == 16000
                    and wav_file.getnframes() > 0
                )
        except (OSError, EOFError, wave.Error):
            return False

    def _build_wake_ack_cache(self, ack_text: str, cache_path) -> bool:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = self._temporary_tts_mp3_path()
        wav_path = cache_path.with_name(
            f".{cache_path.name}.{threading.get_ident()}.{time.time_ns()}.tmp.wav"
        )
        try:
            self._request_tts_mp3(ack_text, mp3_path)
            if not self._convert_tts_to_wav(wav_path, input_path=mp3_path):
                return False
            if not self._wake_ack_cache_valid(wav_path):
                return False
            os.replace(wav_path, cache_path)
            return True
        finally:
            mp3_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)

    def _prewarm_wake_ack_cache(self) -> None:
        if not CONFIG.wake_ack_enable:
            return
        ack_text = CONFIG.wake_ack_text.strip()
        if not ack_text:
            return
        try:
            with self._tts_lock:
                cache_path = self._wake_ack_cache_path(ack_text)
                if self._wake_ack_cache_valid(cache_path):
                    return
                if not self._build_wake_ack_cache(ack_text, cache_path):
                    raise RuntimeError("wake ack cache conversion failed")
            self.get_logger().info(f'[TTS] wake_ack cache ready text="{ack_text}"')
        except Exception as exc:
            self.get_logger().warn(f'Wake ack cache prewarm failed text="{ack_text}": {exc}')

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
        if not CONFIG.thinking_action_enable:
            self._session_record("thinking_action_skipped", reason="disabled", session_id=self._session_id)
            return
        if not CONFIG.action_enable or not CONFIG.action_execute:
            self._session_record("thinking_action_skipped", reason="action_disabled", session_id=self._session_id)
            return
        if not self._action_lock.acquire(blocking=False):
            self.get_logger().warn("Skipping thinking action because another action is still running.")
            self._session_record("thinking_action_skipped", reason="busy", session_id=self._session_id)
            return
        threading.Thread(target=self._run_thinking_action_script, daemon=True).start()

    def _run_thinking_action_script(self) -> None:
        started_at = time.time()
        try:
            command = [
                str(CONFIG.action_runner),
                "--network",
                CONFIG.unitree_network_interface,
                "--id",
                str(CONFIG.thinking_action_id),
            ]
            if CONFIG.thinking_action_release_after_sec > 0:
                command.extend(["--release_after_sec", str(CONFIG.thinking_action_release_after_sec)])
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
                self.get_logger().warn(f"Thinking action failed: {exc}")
                self._session_record(
                    "thinking_action_result",
                    action_id=CONFIG.thinking_action_id,
                    executed=False,
                    reason=str(exc),
                    session_id=self._session_id,
                )
                return
            if completed.stdout:
                self.get_logger().info(f"Thinking action stdout: {completed.stdout.strip()}")
            if completed.stderr:
                self.get_logger().warn(f"Thinking action stderr: {completed.stderr.strip()}")
            executed = completed.returncode == 0
            reason = "runner_completed" if executed else f"runner_exit_{completed.returncode}"
            elapsed_ms = self._elapsed_ms(started_at, time.time())
            self.get_logger().info(
                f"Thinking action: id={CONFIG.thinking_action_id} "
                f"executed={executed} reason={reason} elapsed_ms={elapsed_ms}"
            )
            self._session_record(
                "thinking_action_result",
                action_id=CONFIG.thinking_action_id,
                executed=executed,
                reason=reason,
                elapsed_ms=elapsed_ms,
                session_id=self._session_id,
            )
        finally:
            self._action_lock.release()

    @staticmethod
    def _llm_tts_url() -> str:
        return CONFIG.llm_server_url.rsplit("/", 1)[0] + "/tts/audio"

    def _convert_tts_to_wav_locked(self) -> bool:
        with self._tts_lock:
            return self._convert_tts_to_wav()

    def _convert_tts_to_wav(self, output_path=None, input_path=None) -> bool:
        source_path = input_path or CONFIG.tts_mp3_path
        if not source_path.exists():
            self.get_logger().error(f"{source_path} not found; LLM server did not generate it")
            return False

        target_path = output_path or CONFIG.tts_wav_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(source_path),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(target_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self.get_logger().error(f"ffmpeg conversion failed: {exc}")
            return False

        if not target_path.exists():
            self.get_logger().error(f"{target_path} not generated")
            return False

        self.get_logger().info(f"[TTS] wav_ready path={target_path}")
        return True

    def run_reply_action(
        self,
        reply: str,
        user_text: str = "",
        action_payload: dict[str, Any] | None = None,
        action_generation: int | None = None,
    ) -> None:
        if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
            self._discard_interrupted_turn(self._conversation_session_id, "before_action_lock")
            return
        if not CONFIG.action_enable:
            self._session_record("action_skipped", reason="action_disabled", reply=reply)
            if action_generation is None or not self._interrupt_control.generation_changed(action_generation):
                self._close_session("session_end")
            return
        if not self._action_lock.acquire(blocking=False):
            self.get_logger().warn("Skipping reply action because another action is still running.")
            self._update_status(last_error="action_busy", updated_at=time.time())
            self._session_record("action_skipped", reason="busy", reply=reply)
            if action_generation is None or not self._interrupt_control.generation_changed(action_generation):
                self._close_session("session_end")
            return

        try:
            self._run_reply_action_locked(reply, user_text, action_payload, action_generation)
        finally:
            self._action_lock.release()
            if action_generation is None or not self._interrupt_control.generation_changed(action_generation):
                self._close_session("session_end")

    def _run_reply_action_locked(
        self,
        reply: str,
        user_text: str = "",
        action_payload: dict[str, Any] | None = None,
        action_generation: int | None = None,
    ) -> None:
        started_at = time.time()
        deepseek_action: dict[str, Any] | None = None
        explicit_action: dict[str, Any] | None = None
        semantic_action: dict[str, Any] | None = None

        if action_payload:
            deepseek_action = self._classification_from_deepseek_action(action_payload, reply)

        if not CONFIG.action_frequent_reply_enable:
            classification = deepseek_action
            if classification is None and CONFIG.action_keyword_first and user_text:
                user_payload = self._run_action_classifier(user_text, "keyword")
                if user_payload:
                    user_classification = user_payload.get("classification", {})
                    if self._int_or_default(user_classification.get("action_id"), -1) >= 0:
                        classification = user_classification
            if classification is None and CONFIG.action_backend not in ("deepseek", "none"):
                legacy_payload = self._run_action_classifier(reply, CONFIG.action_backend)
                if legacy_payload:
                    classification = legacy_payload.get("classification", {})
            if classification is None:
                classification = self._no_action_classification(reply, "no_deepseek_action")
            if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
                self._discard_interrupted_turn(self._conversation_session_id, "before_action_execute")
                return
            execution = self._execute_classified_action(classification, action_generation)
            self._log_action_result(
                classification,
                execution,
                started_at,
                reply,
                action_generation,
            )
            return

        if (
            CONFIG.action_keyword_first
            and user_text
            and is_explicit_action_request(user_text)
        ):
            user_payload = self._run_action_classifier(user_text, "keyword")
            if user_payload:
                user_classification = user_payload.get("classification", {})
                if self._int_or_default(user_classification.get("action_id"), -1) >= 0:
                    explicit_action = user_classification

        classification = resolve_reply_action(
            reply=reply,
            user_text=user_text,
            deepseek_action=deepseek_action,
            explicit_action=explicit_action,
            threshold=CONFIG.action_threshold,
            frequent_reply_enabled=CONFIG.action_frequent_reply_enable,
        )

        needs_semantic_fallback = (
            classification.get("backend") == "reply_info_fallback"
            or (action_payload is None and CONFIG.action_backend not in ("deepseek", "none"))
        )
        if needs_semantic_fallback:
            semantic_backend = "keyword"
            if action_payload is None and CONFIG.action_backend not in ("deepseek", "none"):
                semantic_backend = CONFIG.action_backend
            semantic_payload = self._run_action_classifier(reply, semantic_backend)
            if semantic_payload:
                semantic_action = semantic_payload.get("classification", {})
                classification = resolve_reply_action(
                    reply=reply,
                    user_text=user_text,
                    deepseek_action=deepseek_action,
                    explicit_action=explicit_action,
                    semantic_action=semantic_action,
                    threshold=CONFIG.action_threshold,
                    frequent_reply_enabled=CONFIG.action_frequent_reply_enable,
                )

        if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
            self._discard_interrupted_turn(self._conversation_session_id, "before_action_execute")
            return
        execution = self._execute_classified_action(classification, action_generation)
        self._log_action_result(
            classification,
            execution,
            started_at,
            reply,
            action_generation,
        )

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

    def _runner_command(self, action_id: Any, generation: int | None = None) -> list[str]:
        command = [
            str(CONFIG.action_runner),
            "--network",
            CONFIG.unitree_network_interface,
            "--id",
            str(action_id),
        ]
        if generation is not None:
            command.extend(["--generation", str(generation)])
        return command

    def _execute_classified_action(
        self,
        classification: dict[str, Any],
        action_generation: int | None = None,
    ) -> dict[str, Any]:
        action_id = self._int_or_default(classification.get("action_id"), -1)
        if action_id < 0:
            return {"executed": False, "reason": "unknown_action"}
        if not classification.get("should_execute"):
            return {"executed": False, "reason": "score_below_threshold"}
        if not CONFIG.action_execute:
            return {
                "executed": False,
                "reason": "dry_run",
                "would_run": self._runner_command(action_id, action_generation),
            }
        if not CONFIG.unitree_network_interface:
            return {"executed": False, "reason": "--network is required"}
        if not CONFIG.action_runner.exists():
            return {"executed": False, "reason": f"runner not found: {CONFIG.action_runner}"}

        if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
            return {"executed": False, "reason": "stale_before_action_execute"}
        command = self._runner_command(action_id, action_generation)
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
        reply: str,
        action_generation: int | None = None,
    ) -> None:
        self.get_logger().info(
            "[ACTION] "
            f"label={classification.get('label')} "
            f"official={classification.get('official_name')} "
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
            if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
                self._session_record("action_skipped", reason="stale_before_action_release", reply=reply)
                return
            self.get_logger().warn("Arm is holding; running release action 99 and retrying once.")
            if self.release_arm(action_generation):
                retry_execution = self._execute_classified_action(classification, action_generation)
                self.get_logger().info(
                    "Reply action retry: "
                    f"{classification.get('label')} id={classification.get('action_id')} "
                    f"executed={retry_execution.get('executed')} reason={retry_execution.get('reason')}"
                )
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
            if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
                self._session_record("action_skipped", reason="stale_before_action_release", reply=reply)
                return
            self.release_arm(action_generation)

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

    def release_arm(self, action_generation: int | None = None) -> bool:
        if action_generation is not None and self._interrupt_control.generation_changed(action_generation):
            return False
        try:
            completed = subprocess.run(
                self._runner_command(99, action_generation),
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
    node = LlmSurfContextNode()
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
