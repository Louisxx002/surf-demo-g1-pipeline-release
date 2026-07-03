from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from pipeline_log.latency_tracker import read_turn_summaries


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGS_DIR = PROJECT_ROOT / "logs"
STATIC_DIR = PROJECT_ROOT / "ui" / "pipeline_monitor"
IGNORED_LOG_DIRS = {"default", "manual-relay-test"}
PIPELINE_SERVICES = ("surf-voice-runtime", "surf-llm-node", "surf-llm-audio-player")
PIPELINE_ENV_DEFAULTS = {
    "UNITREE_ENABLE": "1",
    "UNITREE_BACKEND": "relay",
    "ROBOT_RELAY_HOST": "192.168.123.164",
    "ROBOT_RELAY_PORT": "9999",
    "ROBOT_RELAY_TIMEOUT_SEC": "15",
    "VOICE_AUDIO_SOURCE": "local",
    "LLM_ACTION_EXECUTE": "1",
    "LLM_ROBOT_SKILL_EXECUTE": "1",
    "SURF_LLM_THINKING_ACK_ENABLE": "0",
    "SURF_LLM_THINKING_ACTION_ENABLE": "0",
    "LLM_THINKING_ACTION_ID": "25",
    "SURF_LLM_WAKE_LISTEN_SEC": "30",
    "LLM_FOLLOWUP_TIMEOUT_SEC": "60",
    "LLM_STANDBY_ACK_ENABLE": "0",
}


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


def _completed_process_payload(result: Any) -> dict[str, Any]:
    return {
        "returncode": int(getattr(result, "returncode", -1)),
        "stdout": str(getattr(result, "stdout", "") or "").strip(),
        "stderr": str(getattr(result, "stderr", "") or "").strip(),
    }


def pipeline_status(command_runner: Any = subprocess.run) -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}
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

    if active_count == len(PIPELINE_SERVICES):
        state = "running"
    elif active_count == 0:
        state = "stopped"
    else:
        state = "partial"

    return {"ok": True, "state": state, "services": services}


def run_pipeline_command(action: str, command_runner: Any = subprocess.run) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        raise ValueError(f"Unsupported pipeline action: {action}")

    env = os.environ.copy()
    env.update(PIPELINE_ENV_DEFAULTS)
    command = ["./scripts/run_pipeline.sh", "--mode", "wake"] if action == "start" else ["./scripts/stop_pipeline.sh"]
    result = command_runner(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
    )
    payload = _completed_process_payload(result)
    payload.update({"ok": payload["returncode"] == 0, "action": action, "command": " ".join(command)})
    return payload


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
            elif parsed.path == "/api/pipeline/status":
                self._serve_pipeline_status()
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

        def _serve_pipeline_status(self) -> None:
            try:
                _json_response(self, pipeline_status())
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(self, {"ok": False, "state": "error", "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _run_pipeline_action(self, action: str) -> None:
            try:
                payload = run_pipeline_command(action)
                status = HTTPStatus.OK if payload["ok"] else HTTPStatus.INTERNAL_SERVER_ERROR
                _json_response(self, payload, status)
            except Exception as exc:  # pragma: no cover - defensive UI endpoint
                _json_response(self, {"ok": False, "action": action, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
