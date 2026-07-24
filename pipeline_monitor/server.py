from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from pipeline_log.latency_tracker import read_turn_summaries
from pipeline_control.interrupt import InterruptControl
from turn_detection.mode_control import TurnModeStore, normalize_mode


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGS_DIR = PROJECT_ROOT / "logs"
STATIC_DIR = PROJECT_ROOT / "ui" / "pipeline_monitor"
IGNORED_LOG_DIRS = {"default", "manual-relay-test"}
PIPELINE_SERVICES = ("surf-voice-runtime", "surf-llm-node", "surf-llm-audio-player")
PIPELINE_START_TIMEOUT_SEC = 480
PIPELINE_STOP_TIMEOUT_SEC = 90
PIPELINE_COMPONENT_LABELS = {
    "surf-voice-runtime": "语音识别",
    "surf-llm-node": "LLM 对话节点",
    "surf-llm-audio-player": "TTS/灯光/动作播放器",
}
PIPELINE_ENV_DEFAULTS = {
    "UNITREE_ENABLE": "1",
    "UNITREE_BACKEND": "relay",
    "ROBOT_RELAY_HOST": "192.168.123.164",
    "ROBOT_RELAY_PORT": "9999",
    "ROBOT_RELAY_TIMEOUT_SEC": "15",
    "VOICE_AUDIO_SOURCE": "robot",
    "VOICE_ROBOT_MIC_IF": "192.168.123.225",
    "VOICE_ROBOT_MIC_PORT": "5556",
    "ROBOT_MIC_PROCESSING_MODE": "beamformer",
    "ROBOT_MIC_SOURCE_CHANNELS": "8",
    "ROBOT_MIC_CHANNEL_MAP": "0,1,2,3",
    "LLM_ACTION_EXECUTE": "1",
    "LLM_ROBOT_SKILL_EXECUTE": "1",
    "SURF_LLM_THINKING_ACK_ENABLE": "1",
    "SURF_LLM_THINKING_ACTION_ENABLE": "0",
    "LLM_THINKING_ACTION_ID": "25",
    "LLM_THINKING_ACK_PLAY_GAP_SEC": "0",
    "LLM_REQUEST_TIMEOUT_SEC": "20",
    "SURF_LLM_WAKE_LISTEN_SEC": "15",
    "LLM_FOLLOWUP_TIMEOUT_SEC": "15",
    "LLM_STANDBY_ACK_ENABLE": "0",
}
ROBOT_SSH_USER = "unitree"
ROBOT_SSH_IDENTITY_FILE = Path.home() / ".ssh" / "surf_robot_ed25519"
ROBOT_MIC_DEVICE_NAME = "Bothlent UAC Dongle"
ROBOT_MIC_RUNTIME_ROOT = "/home/unitree/surf_robot_mic"
ROBOT_MIC_SCRIPT = f"{ROBOT_MIC_RUNTIME_ROOT}/tools/stream_usb_mic.py"
ROBOT_MIC_FILTER = f"{ROBOT_MIC_RUNTIME_ROOT}/filters/DCF_Targ7_runtime.npz"
TURN_MODE_FILENAME = "turn_mode.json"


def turn_mode_status(runtime_dir: Path | None = None) -> dict[str, Any]:
    root = runtime_dir or (PROJECT_ROOT / "runtime")
    mode = TurnModeStore(root / TURN_MODE_FILENAME).read()
    return {
        "ok": True,
        "mode": mode,
        "label": "快速转写" if mode == "basic" else "允许停顿",
    }


def update_turn_mode(
    mode: str,
    *,
    runtime_dir: Path | None = None,
    pipeline_state_getter: Any | None = None,
) -> dict[str, Any]:
    try:
        normalized = normalize_mode(mode)
    except ValueError as exc:
        return {"ok": False, "error": "invalid_mode", "detail": str(exc)}

    state_getter = pipeline_state_getter or (lambda: pipeline_status()["state"])
    state = str(state_getter())
    if state != "stopped":
        return {"ok": False, "error": "session_active", "pipeline_state": state}

    root = runtime_dir or (PROJECT_ROOT / "runtime")
    TurnModeStore(root / TURN_MODE_FILENAME).write(normalized)
    return {"ok": True, "mode": normalized, "pipeline_state": state}


def _robot_mic_settings() -> dict[str, str]:
    # Turn-detection A/B tests must share the same audio front end.
    mode = PIPELINE_ENV_DEFAULTS["ROBOT_MIC_PROCESSING_MODE"]
    channels = os.environ.get("ROBOT_MIC_SOURCE_CHANNELS", PIPELINE_ENV_DEFAULTS["ROBOT_MIC_SOURCE_CHANNELS"])
    channel_map = os.environ.get("ROBOT_MIC_CHANNEL_MAP", PIPELINE_ENV_DEFAULTS["ROBOT_MIC_CHANNEL_MAP"])
    if mode not in {"mean4", "beamformer"}:
        raise ValueError(f"不支持的机器人麦克风处理模式：{mode}")
    if not channels.isdigit() or int(channels) <= 0:
        raise ValueError(f"ROBOT_MIC_SOURCE_CHANNELS 必须是正整数：{channels}")
    if not re.fullmatch(r"\d+(,\d+)*", channel_map):
        raise ValueError(f"ROBOT_MIC_CHANNEL_MAP 格式错误：{channel_map}")
    return {"mode": mode, "channels": channels, "channel_map": channel_map}


def _robot_mic_process_pattern(mic_device: str, port: str, settings: dict[str, str]) -> str:
    return (
        f"[s]tream_usb_mic.py.*--device {re.escape(mic_device)}.*--port {re.escape(port)}"
        f".*--mode {settings['mode']}.*--channels {settings['channels']}"
        f".*--channel-map {re.escape(settings['channel_map'])}"
    )


def detect_robot_mic_device(arecord_output: str) -> str | None:
    for line in arecord_output.splitlines():
        if ROBOT_MIC_DEVICE_NAME not in line:
            continue
        match = re.match(r"^card\s+(\d+):.*device\s+(\d+):", line.strip())
        if match:
            return f"hw:{match.group(1)},{match.group(2)}"
    return None


def _robot_ssh_command(remote_command: str) -> list[str]:
    host = os.environ.get("ROBOT_RELAY_HOST") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_HOST"]
    user = os.environ.get("ROBOT_SSH_USER", ROBOT_SSH_USER)
    identity = Path(os.environ.get("ROBOT_SSH_IDENTITY_FILE", str(ROBOT_SSH_IDENTITY_FILE))).expanduser()
    return [
        "ssh",
        "-i",
        str(identity),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=3",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        remote_command,
    ]


def _is_session_log(path: Path) -> bool:
    return (
        path.name == "pipeline.log"
        and path.parent.name not in IGNORED_LOG_DIRS
        and path.parent.name[:8].isdigit()
    )


def iter_pipeline_logs(logs_dir: Path) -> Iterable[Path]:
    if not logs_dir.exists():
        return []
    return (path for path in logs_dir.glob("*/pipeline.log") if _is_session_log(path))


def find_latest_pipeline_log(logs_dir: Path = DEFAULT_LOGS_DIR) -> Path | None:
    candidates = list(iter_pipeline_logs(logs_dir))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_pipeline_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _compact_meta(entry: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {key: entry[key] for key in keys if key in entry and entry[key] not in ("", None)}


def event_view(entry: dict[str, Any]) -> dict[str, Any]:
    stage = str(entry.get("stage", "unknown"))
    title = stage.upper()
    kind = "system"
    message = stage
    meta: dict[str, Any] = {}

    if stage in {"wake", "wake_received"}:
        kind = "wake"
        title = "WAKE"
        message = str(entry.get("wake_word", ""))
        meta = _compact_meta(entry, ("session_id",))
    elif stage == "speaker_id":
        kind = "speaker"
        title = "SPEAKER"
        message = str(entry.get("label", ""))
        meta = _compact_meta(entry, ("score", "session_id"))
    elif stage in {"asr_result", "asr_received"}:
        kind = "asr"
        title = "ASR"
        message = str(entry.get("text", ""))
        meta = _compact_meta(entry, ("speaker", "duration_sec", "session_id"))
    elif stage == "llm_reply":
        kind = "llm"
        title = "LLM"
        message = str(entry.get("reply", ""))
        meta = _compact_meta(entry, ("timing", "session_id"))
    elif stage == "llm_failed":
        kind = "error"
        title = "LLM_FAILED"
        message = str(entry.get("error", "")) or "llm_failed"
        meta = _compact_meta(entry, ("timeout_sec", "session_id"))
    elif stage in {"tts_ready", "wake_ack_ready", "standby_ack_ready"}:
        kind = "tts"
        title = "TTS"
        message = str(entry.get("text", stage))
        meta = _compact_meta(entry, ("reason", "session_id"))
    elif stage in {"tts_play_started", "tts_play_finished"}:
        kind = "play"
        title = "PLAY"
        message = str(entry.get("text") or entry.get("kind") or stage)
        meta = _compact_meta(entry, ("kind", "wav", "session_id"))
    elif stage == "action_result":
        kind = "action"
        title = "ACTION"
        label = str(entry.get("label", ""))
        action_id = entry.get("action_id", "")
        executed = entry.get("executed", "")
        message = f"{label} id={action_id} executed={executed}"
        meta = _compact_meta(entry, ("official_name", "score", "backend", "reason", "executed", "session_id"))
    elif stage.startswith("standby_ack"):
        kind = "standby"
        title = "STANDBY"
        message = str(entry.get("reason", stage))
        meta = _compact_meta(entry, ("enabled", "empty_text", "session_id"))
    elif stage == "terminate_command":
        kind = "state"
        title = "SESSION"
        message = "用户主动关闭当前会话"
        meta = _compact_meta(entry, ("session_id",))
    elif stage == "manual_interrupt":
        listening_opened = bool(entry.get("listening_opened"))
        kind = "state" if listening_opened else "error"
        title = "INTERRUPT" if listening_opened else "INTERRUPT_FAILED"
        message = "已打断，正在听取" if listening_opened else "打断未完成"
        meta = _compact_meta(
            entry,
            ("generation", "request_id", "partial", "listening_opened", "errors", "session_id"),
        )
    elif stage == "turn_shadow_comparison":
        kind = "shadow"
        title = "SHADOW"
        baseline = entry.get("baseline") if isinstance(entry.get("baseline"), dict) else {}
        shadow = entry.get("shadow") if isinstance(entry.get("shadow"), dict) else {}
        baseline_decision = str(baseline.get("decision", "unknown"))
        shadow_decision = str(shadow.get("decision", "unknown"))
        message = f"baseline={baseline_decision} shadow={shadow_decision}"
        meta = _compact_meta(
            entry,
            (
                "comparison_id",
                "context",
                "status",
                "agreement",
                "delta_ms",
                "read_only",
                "dropped_frames",
                "session_id",
            ),
        )
    elif stage == "followup_closed":
        kind = "state"
        title = "SESSION"
        reason = str(entry.get("reason", stage))
        message = "当前会话已关闭" if reason in {"timeout", "followup_timeout"} else f"当前会话已关闭：{reason}"
        meta = _compact_meta(entry, ("reason", "session_id"))
    elif stage == "followup_open":
        kind = "state"
        title = "SESSION"
        message = "等待继续追问"
        meta = _compact_meta(entry, ("timeout_sec", "reason", "session_id"))
    elif stage.startswith("followup") or stage.startswith("wake_listen"):
        kind = "state"
        title = "STATE"
        message = str(entry.get("reason", stage))
        meta = _compact_meta(entry, ("timeout_sec", "session_id"))

    return {
        "time": entry.get("time", ""),
        "elapsed_sec": entry.get("elapsed_sec", ""),
        "stage": stage,
        "kind": kind,
        "title": title,
        "message": message,
        "meta": meta,
        "raw": entry,
    }


def read_existing_events(log_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not log_path.exists():
        return events
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        payload = parse_pipeline_line(line)
        if payload is not None:
            events.append(event_view(payload))
    if limit and len(events) > limit:
        return events[-limit:]
    return events


def read_shadow_comparisons(
    shadow_path: Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    if not shadow_path.exists():
        return []
    for line in shadow_path.read_text(encoding="utf-8", errors="replace").splitlines():
        payload = parse_pipeline_line(line)
        if payload is None:
            continue
        event_id = str(payload.get("event_id", ""))
        detector_name = str(payload.get("detector_name", ""))
        if not event_id or not detector_name:
            continue
        suffix = f":{detector_name}"
        comparison_id = event_id[: -len(suffix)] if event_id.endswith(suffix) else event_id
        item = grouped.setdefault(
            comparison_id,
            {
                "comparison_id": comparison_id,
                "session_id": str(payload.get("session_id", "")),
                "timestamp": payload.get("timestamp", 0),
                "text": str(payload.get("final_text") or payload.get("partial_text") or ""),
                "agent_playing": bool(payload.get("agent_playing")),
                "detectors": {},
                "read_only": True,
            },
        )
        item["detectors"][detector_name] = {
            "decision": str(payload.get("decision", "UNCERTAIN")),
            "confidence": payload.get("confidence", 0),
            "reason": str(payload.get("reason", "")),
            "latency_ms": payload.get("detector_latency_ms", 0),
        }
    comparisons = list(grouped.values())
    for item in comparisons:
        decisions = {
            detector["decision"] for detector in item["detectors"].values()
        }
        item["agreement"] = len(decisions) <= 1 and len(item["detectors"]) > 1
    comparisons.sort(key=lambda item: float(item.get("timestamp") or 0), reverse=True)
    return comparisons[:limit]


def _completed_process_payload(result: Any) -> dict[str, Any]:
    return {
        "returncode": int(getattr(result, "returncode", -1)),
        "stdout": str(getattr(result, "stdout", "") or "").strip(),
        "stderr": str(getattr(result, "stderr", "") or "").strip(),
    }


def robot_relay_status(
    host: str | None = None,
    port: str | int | None = None,
    timeout_sec: float = 1.5,
) -> dict[str, Any]:
    host = host or os.environ.get("ROBOT_RELAY_HOST") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_HOST"]
    port = int(port or os.environ.get("ROBOT_RELAY_PORT") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_PORT"])
    endpoint = f"{host}:{port}"
    hint = f"ssh unitree@{host} 后运行：cd ~/surf_robot_relay && ./scripts/run_jetson_robot_relay.sh"
    started_at = time.time()
    try:
        from robot_relay.robot_relay_client import RobotRelayClient

        response = RobotRelayClient(host, port, timeout_sec=timeout_sec).health()
        ok = bool(response.get("ok"))
        return {
            "ready": ok,
            "state": "ready" if ok else "not_ready",
            "endpoint": endpoint,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "response": response,
            "hint": "" if ok else hint,
        }
    except Exception as exc:
        return {
            "ready": False,
            "state": "not_ready",
            "endpoint": endpoint,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "error": str(exc),
            "hint": hint,
        }


def robot_mic_status(command_runner: Any = subprocess.run) -> dict[str, Any]:
    host = os.environ.get("ROBOT_RELAY_HOST") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_HOST"]
    destination = os.environ.get("VOICE_ROBOT_MIC_IF") or PIPELINE_ENV_DEFAULTS["VOICE_ROBOT_MIC_IF"]
    port = os.environ.get("VOICE_ROBOT_MIC_PORT") or PIPELINE_ENV_DEFAULTS["VOICE_ROBOT_MIC_PORT"]
    started_at = time.time()
    try:
        settings = _robot_mic_settings()
        device_result = command_runner(
            _robot_ssh_command("arecord -l"),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
        device_payload = _completed_process_payload(device_result)
        mic_device = detect_robot_mic_device(device_payload["stdout"])
        if device_payload["returncode"] != 0 or mic_device is None:
            error = device_payload["stderr"] or f"未找到 {ROBOT_MIC_DEVICE_NAME}"
            return {
                "ready": False,
                "state": "not_ready",
                "endpoint": f"{destination}:{port}",
                "elapsed_ms": int((time.time() - started_at) * 1000),
                "process": "",
                "error": error,
                "hint": f"机器人未识别到外置麦克风 {ROBOT_MIC_DEVICE_NAME}",
            }

        process_pattern = _robot_mic_process_pattern(mic_device, port, settings)
        remote_command = f"pgrep -af {shlex.quote(process_pattern)}"
        result = command_runner(
            _robot_ssh_command(remote_command),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
        payload = _completed_process_payload(result)
        ready = payload["returncode"] == 0 and bool(payload["stdout"])
        hint = (
            f"先安装免密公钥，再确认机器人外置麦克风：ssh {ROBOT_SSH_USER}@{host}；"
            f"设备 {ROBOT_MIC_DEVICE_NAME}，目标 {destination}:{port}"
        )
        return {
            "ready": ready,
            "state": "ready" if ready else "not_ready",
            "endpoint": f"{destination}:{port}",
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "device": mic_device,
            "processing_mode": settings["mode"],
            "source_channels": settings["channels"],
            "channel_map": settings["channel_map"],
            "process": payload["stdout"],
            "error": payload["stderr"] if not ready else "",
            "hint": "" if ready else hint,
        }
    except Exception as exc:
        return {
            "ready": False,
            "state": "not_ready",
            "endpoint": f"{destination}:{port}",
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "error": str(exc),
            "hint": f"机器人 SSH 不可用；确认机器人开机并安装 {ROBOT_SSH_IDENTITY_FILE.name}.pub",
        }


def ensure_robot_runtime(
    command_runner: Any = subprocess.run,
    relay_checker: Any = robot_relay_status,
    mic_checker: Any = robot_mic_status,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    destination = os.environ.get("VOICE_ROBOT_MIC_IF") or PIPELINE_ENV_DEFAULTS["VOICE_ROBOT_MIC_IF"]
    port = os.environ.get("VOICE_ROBOT_MIC_PORT") or PIPELINE_ENV_DEFAULTS["VOICE_ROBOT_MIC_PORT"]
    try:
        settings = _robot_mic_settings()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        device_result = command_runner(
            _robot_ssh_command("arecord -l"),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return {"ok": False, "error": f"机器人麦克风设备查询失败：{exc}"}

    device_payload = _completed_process_payload(device_result)
    mic_device = detect_robot_mic_device(device_payload["stdout"])
    if device_payload["returncode"] != 0 or mic_device is None:
        error = device_payload["stderr"] or f"未找到 {ROBOT_MIC_DEVICE_NAME}"
        return {"ok": False, "error": f"机器人外置麦克风不可用：{error}", **device_payload}

    required_paths = [ROBOT_MIC_SCRIPT, f"{ROBOT_MIC_RUNTIME_ROOT}/beamforming/mic_runtime.py"]
    if settings["mode"] == "beamformer":
        required_paths.append(ROBOT_MIC_FILTER)
    runtime_probe_command = " && ".join(
        f"test -r {shlex.quote(path)}" for path in required_paths
    ) + " && echo runtime-ready"
    try:
        runtime_probe_result = command_runner(
            _robot_ssh_command(runtime_probe_command),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return {"ok": False, "error": f"机器人麦克风 runtime 检查失败：{exc}"}
    runtime_probe_payload = _completed_process_payload(runtime_probe_result)
    if runtime_probe_payload["returncode"] != 0:
        return {
            "ok": False,
            "error": "机器人缺少新版麦克风 runtime；请先运行 ./scripts/deploy_robot_mic_runtime.sh",
            **runtime_probe_payload,
        }

    expected_mic_pattern = _robot_mic_process_pattern(mic_device, port, settings)
    stale_mic_pattern = f"[s]tream_usb_mic.py.*--port {port}"
    cleanup_command = " ".join(
        [
            f"if pgrep -f '{stale_mic_pattern}' >/dev/null",
            f"&& ! pgrep -f '{expected_mic_pattern}' >/dev/null; then",
            f"pkill -f '{stale_mic_pattern}' || true;",
            "fi",
        ]
    )
    try:
        cleanup_result = command_runner(
            _robot_ssh_command(cleanup_command),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return {"ok": False, "error": f"机器人旧麦克风推流清理失败：{exc}"}

    cleanup_payload = _completed_process_payload(cleanup_result)
    if cleanup_payload["returncode"] != 0:
        error = cleanup_payload["stderr"] or cleanup_payload["stdout"] or "unknown SSH failure"
        return {"ok": False, "error": f"机器人旧麦克风推流清理失败：{error}", **cleanup_payload}

    try:
        probe_result = command_runner(
            _robot_ssh_command(f"pgrep -af '{expected_mic_pattern}'"),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        return {"ok": False, "error": f"机器人麦克风推流状态查询失败：{exc}"}

    probe_payload = _completed_process_payload(probe_result)
    mic_running = probe_payload["returncode"] == 0 and bool(probe_payload["stdout"])
    remote_parts = [
        "set -eu;",
        f"mkdir -p ~/surf_robot_relay/logs {ROBOT_MIC_RUNTIME_ROOT}/logs;",
        "if ! pgrep -f '[j]etson_robot_relay.py' >/dev/null; then",
        "setsid -f ~/surf_robot_relay/scripts/run_jetson_robot_relay.sh",
        "> ~/surf_robot_relay/logs/jetson_robot_relay.log 2>&1 </dev/null;",
        "fi;",
    ]
    if not mic_running:
        mic_command = [
            "env",
            f"PYTHONPATH={ROBOT_MIC_RUNTIME_ROOT}",
            "/usr/bin/python3",
            ROBOT_MIC_SCRIPT,
            "--device",
            mic_device,
            "--dest",
            destination,
            "--port",
            port,
            "--mode",
            settings["mode"],
            "--channels",
            settings["channels"],
            "--channel-map",
            settings["channel_map"],
        ]
        if settings["mode"] == "beamformer":
            mic_command.extend(["--filter", ROBOT_MIC_FILTER])
        remote_parts.extend(
            [
                "setsid -f " + " ".join(shlex.quote(part) for part in mic_command),
                f"> {ROBOT_MIC_RUNTIME_ROOT}/logs/stream_usb_mic.log 2>&1 </dev/null;",
            ]
        )
    remote_parts.append("echo robot-runtime-ready")
    remote_command = " ".join(remote_parts)
    try:
        result = command_runner(
            _robot_ssh_command(remote_command),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=12,
        )
    except Exception as exc:
        return {"ok": False, "error": f"机器人 SSH 启动失败：{exc}"}

    payload = _completed_process_payload(result)
    if payload["returncode"] != 0:
        error = payload["stderr"] or payload["stdout"] or "unknown SSH failure"
        return {"ok": False, "error": f"机器人端服务启动失败：{error}", **payload}

    relay: dict[str, Any] = {"ready": False}
    mic: dict[str, Any] = {"ready": False}
    for _ in range(12):
        relay = relay_checker()
        mic = mic_checker()
        if relay.get("ready") and mic.get("ready"):
            return {"ok": True, "relay_ready": True, "mic_ready": True, **payload}
        sleep(0.5)

    return {
        "ok": False,
        "error": "机器人端 relay 或外置麦克风推流未就绪",
        "relay": relay,
        "mic": mic,
        **payload,
    }


def pipeline_status(
    command_runner: Any = subprocess.run,
    relay_checker: Any = robot_relay_status,
    mic_checker: Any = robot_mic_status,
) -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}
    components: dict[str, dict[str, Any]] = {}
    active_count = 0
    for service in PIPELINE_SERVICES:
        result = command_runner(
            ["systemctl", "--user", "is-active", service],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
        state = str(getattr(result, "stdout", "") or "").strip()
        is_active = state == "active"
        active_count += int(is_active)
        services[service] = {
            "state": state or "unknown",
            "active": is_active,
            "returncode": int(getattr(result, "returncode", -1)),
        }
        components[service] = {
            "label": PIPELINE_COMPONENT_LABELS.get(service, service),
            "ready": is_active,
            "state": "ready" if is_active else (state or "unknown"),
            "hint": f"本机服务未运行：{service}",
        }

    relay = relay_checker()
    components["robot_relay"] = {
        "label": "机器人中转服务",
        "ready": bool(relay.get("ready")),
        "state": str(relay.get("state", "unknown")),
        "endpoint": str(relay.get("endpoint", "")),
        "hint": str(relay.get("hint", "")),
        "elapsed_ms": relay.get("elapsed_ms", ""),
    }
    mic = mic_checker()
    mic_mode = str(mic.get("processing_mode", ""))
    mic_channels = str(mic.get("source_channels", ""))
    mic_channel_map = str(mic.get("channel_map", ""))
    mic_detail_parts = []
    if mic_mode:
        mic_detail_parts.append(mic_mode)
    if mic_channels:
        mic_detail_parts.append(f"{mic_channels}ch")
    if mic_channel_map:
        mic_detail_parts.append(f"channels {mic_channel_map}")
    components["robot_mic"] = {
        "label": "机器人外置麦克风推流",
        "ready": bool(mic.get("ready")),
        "state": str(mic.get("state", "unknown")),
        "endpoint": str(mic.get("endpoint", "")),
        "hint": str(mic.get("hint", "")),
        "elapsed_ms": mic.get("elapsed_ms", ""),
        "detail": " | ".join(mic_detail_parts),
    }

    if active_count == len(PIPELINE_SERVICES) and relay.get("ready") and mic.get("ready"):
        state = "running"
    elif active_count == 0:
        state = "stopped"
    else:
        state = "partial"

    return {
        "ok": True,
        "state": state,
        "services": services,
        "components": components,
        "relay": relay,
        "robot_mic": mic,
    }


def run_pipeline_command(
    action: str,
    command_runner: Any = subprocess.run,
    robot_runtime_starter: Any = ensure_robot_runtime,
    services_ready_checker: Any | None = None,
) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        raise ValueError(f"Unsupported pipeline action: {action}")

    env = os.environ.copy()
    env.update(PIPELINE_ENV_DEFAULTS)
    if action == "start":
        robot_runtime = robot_runtime_starter()
        if not robot_runtime.get("ok"):
            return {
                "ok": False,
                "action": action,
                "returncode": -1,
                "stdout": "",
                "stderr": str(robot_runtime.get("error", "robot runtime unavailable")),
                "error": str(robot_runtime.get("error", "robot runtime unavailable")),
                "robot_runtime": robot_runtime,
            }
    command = ["./scripts/run_pipeline.sh", "--mode", "wake"] if action == "start" else ["./scripts/stop_pipeline.sh"]
    timeout_sec = PIPELINE_START_TIMEOUT_SEC if action == "start" else PIPELINE_STOP_TIMEOUT_SEC
    try:
        result = command_runner(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "action": action,
            "returncode": -1,
            "stdout": str(exc.stdout or ""),
            "stderr": str(exc.stderr or ""),
            "error": f"Pipeline {action} 超过 {timeout_sec} 秒仍未完成",
            "command": " ".join(command),
        }
    payload = _completed_process_payload(result)
    payload.update({"ok": payload["returncode"] == 0, "action": action, "command": " ".join(command)})
    if action == "start" and payload["ok"]:
        readiness_check = services_ready_checker or _pipeline_services_running
        if readiness_check():
            return payload
        payload["ok"] = False
        payload["error"] = "Pipeline 启动命令已结束，但本机服务未全部就绪"
    return payload


def _pipeline_services_running(command_runner: Any = subprocess.run) -> bool:
    for service in PIPELINE_SERVICES:
        result = command_runner(
            ["systemctl", "--user", "is-active", service],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
        )
        if str(getattr(result, "stdout", "") or "").strip() != "active":
            return False
    return True


def _make_robot_relay_client() -> Any:
    from robot_relay.robot_relay_client import RobotRelayClient

    host = os.environ.get("ROBOT_RELAY_HOST") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_HOST"]
    port = int(os.environ.get("ROBOT_RELAY_PORT") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_PORT"])
    timeout_sec = float(
        os.environ.get("ROBOT_RELAY_TIMEOUT_SEC") or PIPELINE_ENV_DEFAULTS["ROBOT_RELAY_TIMEOUT_SEC"]
    )
    return RobotRelayClient(host, port, timeout_sec=timeout_sec)


def run_pipeline_interrupt(
    logs_dir: Path = DEFAULT_LOGS_DIR,
    pipeline_running_checker: Any = _pipeline_services_running,
    relay_client_factory: Any = _make_robot_relay_client,
    interrupt_control: InterruptControl | None = None,
    followup_timeout_sec: float | None = None,
) -> dict[str, Any]:
    if not pipeline_running_checker():
        return {"ok": False, "partial": False, "error": "pipeline_not_running"}

    latest_log = find_latest_pipeline_log(logs_dir)
    session_id = latest_log.parent.name if latest_log is not None else ""
    timeout_sec = float(
        followup_timeout_sec
        if followup_timeout_sec is not None
        else os.environ.get("LLM_FOLLOWUP_TIMEOUT_SEC", PIPELINE_ENV_DEFAULTS["LLM_FOLLOWUP_TIMEOUT_SEC"])
    )
    control = interrupt_control or InterruptControl(PROJECT_ROOT / "runtime")
    errors: list[str] = []
    stop_audio: dict[str, Any] | None = None
    release_arm: dict[str, Any] | None = None

    # Invalidate in-flight LLM/TTS/action work before waiting on robot RPCs.
    # This closes the race where a slow relay response lets stale work land.
    try:
        command = control.begin(session_id=session_id)
    except Exception as exc:
        return {"ok": False, "partial": False, "error": f"interrupt_begin: {exc}"}

    generation = int(command["generation"])
    listening_opened = False
    try:
        relay = relay_client_factory()
    except Exception as exc:
        relay = None
        errors.append(f"relay_client: {exc}")

    try:
        if relay is None:
            raise RuntimeError("relay client unavailable")
        stop_audio = relay.stop_audio("tts", generation=generation)
        if not isinstance(stop_audio, dict):
            errors.append("stop_audio returned an invalid response")
        elif int(stop_audio.get("ret", -1)) != 0:
            errors.append(f"stop_audio returned ret={stop_audio.get('ret', 'missing')}")
    except Exception as exc:
        errors.append(f"stop_audio: {exc}")

    try:
        if relay is None:
            raise RuntimeError("relay client unavailable")
        release_arm = relay.release_arm(generation=generation)
        if not isinstance(release_arm, dict):
            errors.append("release_arm returned an invalid response")
        elif int(release_arm.get("ret", -1)) != 0:
            errors.append(f"release_arm returned ret={release_arm.get('ret', 'missing')}")
    except Exception as exc:
        errors.append(f"release_arm: {exc}")

    stop_succeeded = isinstance(stop_audio, dict) and int(stop_audio.get("ret", -1)) == 0
    release_succeeded = isinstance(release_arm, dict) and int(release_arm.get("ret", -1)) == 0
    if stop_succeeded and release_succeeded:
        try:
            control.open_listening(command, followup_timeout_sec=timeout_sec)
            listening_opened = True
        except Exception as exc:
            errors.append(f"open_listening: {exc}")

    partial = bool(errors)
    if latest_log is not None:
        event = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "stage": "manual_interrupt",
            "session_id": session_id,
            "request_id": command["request_id"],
            "generation": command["generation"],
            "partial": partial,
            "listening_opened": listening_opened,
            "errors": errors,
        }
        with latest_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {
        "ok": not errors,
        "partial": partial,
        "message": (
            "已打断，正在听取"
            if listening_opened and not partial
            else "打断未完成：动作未安全释放"
            if stop_succeeded and not release_succeeded
            else "打断未完成：机器人停音失败"
        ),
        "session_id": session_id,
        "request_id": command["request_id"],
        "generation": command["generation"],
        "listening_opened": listening_opened,
        "stop_audio": stop_audio,
        "release_arm": release_arm,
        "errors": errors,
    }


def run_pipeline_end_session(
    logs_dir: Path = DEFAULT_LOGS_DIR,
    pipeline_running_checker: Any = _pipeline_services_running,
    relay_client_factory: Any = _make_robot_relay_client,
    interrupt_control: InterruptControl | None = None,
) -> dict[str, Any]:
    if not pipeline_running_checker():
        return {"ok": False, "partial": False, "error": "pipeline_not_running"}

    latest_log = find_latest_pipeline_log(logs_dir)
    session_id = latest_log.parent.name if latest_log is not None else ""
    control = interrupt_control or InterruptControl(PROJECT_ROOT / "runtime")
    command = control.begin(session_id=session_id)
    generation = int(command["generation"])
    errors: list[str] = []
    stop_audio: dict[str, Any] | None = None
    release_arm: dict[str, Any] | None = None

    try:
        relay = relay_client_factory()
        stop_audio = relay.stop_audio("tts", generation=generation)
        if not isinstance(stop_audio, dict) or int(stop_audio.get("ret", -1)) != 0:
            errors.append(f"stop_audio returned ret={stop_audio.get('ret', 'missing') if isinstance(stop_audio, dict) else 'invalid'}")
        release_arm = relay.release_arm(generation=generation)
        if not isinstance(release_arm, dict) or int(release_arm.get("ret", -1)) != 0:
            errors.append(f"release_arm returned ret={release_arm.get('ret', 'missing') if isinstance(release_arm, dict) else 'invalid'}")
    except Exception as exc:
        errors.append(str(exc))

    try:
        command = control.request_session_end(
            session_id=session_id,
            user_text="",
            command=command,
        )
    except Exception as exc:
        errors.append(f"request_session_end: {exc}")

    if latest_log is not None:
        event = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "stage": "manual_session_end",
            "session_id": session_id,
            "request_id": command["request_id"],
            "generation": generation,
            "partial": bool(errors),
            "errors": errors,
        }
        with latest_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {
        "ok": not errors,
        "partial": bool(errors),
        "message": "正在关闭当前会话" if not errors else "会话已请求关闭，但机器人停音或复位未完成",
        "session_id": session_id,
        "request_id": command["request_id"],
        "generation": generation,
        "stop_audio": stop_audio,
        "release_arm": release_arm,
        "errors": errors,
    }


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_handler(logs_dir: Path) -> type[BaseHTTPRequestHandler]:
    class PipelineMonitorHandler(BaseHTTPRequestHandler):
        server_version = "SURFPipelineMonitor/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._serve_static("index.html")
            elif parsed.path.startswith("/static/"):
                self._serve_static(parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/latest-log":
                self._serve_latest_log()
            elif parsed.path == "/api/events":
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["200"])[0])
                self._serve_events(limit=limit)
            elif parsed.path == "/api/turns":
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["20"])[0])
                self._serve_turns(limit=limit)
            elif parsed.path == "/api/shadow":
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["20"])[0])
                self._serve_shadow(limit=limit)
            elif parsed.path == "/api/pipeline/status":
                self._serve_pipeline_status()
            elif parsed.path == "/api/turn-mode":
                _json_response(self, turn_mode_status())
            elif parsed.path == "/events":
                self._serve_sse()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/pipeline/start":
                self._run_pipeline_action("start")
            elif parsed.path == "/api/pipeline/stop":
                self._run_pipeline_action("stop")
            elif parsed.path == "/api/pipeline/interrupt":
                self._run_pipeline_interrupt()
            elif parsed.path == "/api/pipeline/end-session":
                self._run_pipeline_end_session()
            elif parsed.path == "/api/turn-mode":
                self._update_turn_mode()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _serve_static(self, relative_path: str) -> None:
            target = (STATIC_DIR / relative_path).resolve()
            if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = target.read_bytes()
            content_type, _ = mimetypes.guess_type(str(target))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_latest_log(self) -> None:
            latest = find_latest_pipeline_log(logs_dir)
            if latest is None:
                _json_response(self, {"ok": False, "log_path": None})
                return
            _json_response(
                self,
                {
                    "ok": True,
                    "log_path": str(latest),
                    "session_id": latest.parent.name,
                    "mtime": latest.stat().st_mtime,
                },
            )

        def _serve_events(self, limit: int = 200) -> None:
            latest = find_latest_pipeline_log(logs_dir)
            if latest is None:
                _json_response(self, {"ok": False, "events": [], "turn_summaries": []})
                return
            _json_response(
                self,
                {
                    "ok": True,
                    "log_path": str(latest),
                    "session_id": latest.parent.name,
                    "events": read_existing_events(latest, limit=limit),
                    "turn_summaries": read_turn_summaries(latest, limit=20),
                },
            )

        def _serve_turns(self, limit: int = 20) -> None:
            latest = find_latest_pipeline_log(logs_dir)
            if latest is None:
                _json_response(self, {"ok": False, "turn_summaries": []})
                return
            _json_response(
                self,
                {
                    "ok": True,
                    "log_path": str(latest),
                    "session_id": latest.parent.name,
                    "turn_summaries": read_turn_summaries(latest, limit=limit),
                },
            )

        def _serve_shadow(self, limit: int = 20) -> None:
            latest = find_latest_pipeline_log(logs_dir)
            if latest is None:
                _json_response(self, {"ok": False, "enabled": False, "comparisons": []})
                return
            shadow_path = latest.parent / "turn_shadow.jsonl"
            _json_response(
                self,
                {
                    "ok": True,
                    "enabled": shadow_path.exists(),
                    "read_only": True,
                    "session_id": latest.parent.name,
                    "comparisons": read_shadow_comparisons(shadow_path, limit=limit),
                },
            )

        def _serve_pipeline_status(self) -> None:
            try:
                _json_response(self, pipeline_status())
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(self, {"ok": False, "state": "error", "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _update_turn_mode(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                result = update_turn_mode(str(payload.get("mode", "")))
                if result.get("ok"):
                    status = HTTPStatus.OK
                elif result.get("error") == "session_active":
                    status = HTTPStatus.CONFLICT
                else:
                    status = HTTPStatus.BAD_REQUEST
                _json_response(self, result, status)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                _json_response(
                    self,
                    {"ok": False, "error": "invalid_request", "detail": str(exc)},
                    HTTPStatus.BAD_REQUEST,
                )

        def _run_pipeline_action(self, action: str) -> None:
            try:
                payload = run_pipeline_command(action)
                status = HTTPStatus.OK if payload["ok"] else HTTPStatus.INTERNAL_SERVER_ERROR
                _json_response(self, payload, status)
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(self, {"ok": False, "action": action, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _run_pipeline_interrupt(self) -> None:
            try:
                payload = run_pipeline_interrupt(logs_dir=logs_dir)
                if payload.get("error") == "pipeline_not_running":
                    status = HTTPStatus.CONFLICT
                elif payload.get("ok") or payload.get("partial"):
                    status = HTTPStatus.OK
                else:
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                _json_response(self, payload, status)
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(
                    self,
                    {"ok": False, "partial": False, "error": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _run_pipeline_end_session(self) -> None:
            try:
                payload = run_pipeline_end_session(logs_dir=logs_dir)
                if payload.get("error") == "pipeline_not_running":
                    status = HTTPStatus.CONFLICT
                elif payload.get("ok") or payload.get("partial"):
                    status = HTTPStatus.OK
                else:
                    status = HTTPStatus.INTERNAL_SERVER_ERROR
                _json_response(self, payload, status)
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(
                    self,
                    {"ok": False, "partial": False, "error": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _serve_sse(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            current_log: Path | None = None
            position = 0
            while True:
                latest = find_latest_pipeline_log(logs_dir)
                if latest is None:
                    self._send_sse({"kind": "system", "title": "WAIT", "message": "等待 pipeline.log"})
                    time.sleep(1.0)
                    continue
                if latest != current_log:
                    current_log = latest
                    position = 0
                    self._send_sse(
                        {
                            "kind": "system",
                            "title": "LOG",
                            "message": f"跟踪 {latest.parent.name}",
                            "log_path": str(latest),
                        }
                    )
                try:
                    with latest.open("r", encoding="utf-8", errors="replace") as f:
                        f.seek(position)
                        for line in f:
                            payload = parse_pipeline_line(line)
                            if payload is not None:
                                self._send_sse(event_view(payload))
                        position = f.tell()
                    time.sleep(0.35)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except OSError as exc:
                    self._send_sse({"kind": "system", "title": "ERROR", "message": str(exc)})
                    time.sleep(1.0)

        def _send_sse(self, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

    return PipelineMonitorHandler


def run_server(host: str, port: int, logs_dir: Path) -> None:
    handler = make_handler(logs_dir)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"SURF pipeline monitor: http://{host}:{port}")
    print(f"logs dir: {logs_dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nmonitor stopped")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the read-only SURF pipeline monitor UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS_DIR)
    args = parser.parse_args()
    run_server(args.host, args.port, args.logs_dir)


if __name__ == "__main__":
    main()
