from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_COMMAND_LOCK = threading.RLock()


class InterruptControl:
    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.command_path = self.runtime_dir / "interrupt_command.json"
        self.session_command_path = self.runtime_dir / "session_command.json"
        self.followup_path = self.runtime_dir / "followup_control.json"
        self.tts_guard_path = self.runtime_dir / "tts_guard.json"

    def current_generation(self) -> int:
        payload = self._read_json(self.command_path)
        try:
            return max(0, int(payload.get("generation", 0)))
        except (TypeError, ValueError):
            return 0

    def generation_changed(self, generation: int) -> bool:
        return self.current_generation() != int(generation)

    def playback_active(self, now: float | None = None) -> bool:
        payload = self._read_json(self.tts_guard_path)
        if not bool(payload.get("active", False)):
            return False
        try:
            guard_until = float(payload.get("guard_until", 0.0))
        except (TypeError, ValueError):
            return False
        return guard_until > float(time.time() if now is None else now)

    def read_session_command(self) -> dict[str, Any]:
        return self._read_json(self.session_command_path)

    def wait_until(self, deadline: float, generation: int, poll_sec: float = 0.05) -> bool:
        """Wait for a wall-clock deadline, returning False when interrupted."""
        while True:
            if self.generation_changed(generation):
                return False
            remaining = float(deadline) - time.time()
            if remaining <= 0:
                return True
            time.sleep(min(max(0.001, float(poll_sec)), remaining))

    def begin(self, session_id: str = "") -> dict[str, Any]:
        """Invalidate existing work without opening the microphone yet."""
        with _COMMAND_LOCK:
            now = time.time()
            payload = {
                "command": "interrupt_and_listen",
                "request_id": uuid.uuid4().hex,
                "generation": self.current_generation() + 1,
                "session_id": str(session_id),
                "updated_at": now,
            }
            self._atomic_write(self.command_path, payload)
        return payload

    def open_listening(
        self,
        command: dict[str, Any],
        followup_timeout_sec: float = 15.0,
    ) -> None:
        """Clear playback guards and open follow-up after robot stop succeeds."""
        with _COMMAND_LOCK:
            generation = int(command.get("generation", -1))
            if generation != self.current_generation():
                raise RuntimeError(
                    f"stale interrupt generation={generation} current={self.current_generation()}"
                )
            now = time.time()
            session_id = str(command.get("session_id", ""))
            self._atomic_write(
                self.tts_guard_path,
                {
                    "active": False,
                    "kind": "manual_interrupt",
                    "text": "",
                    "session_id": session_id,
                    "ended_at": now,
                    "guard_until": now,
                    "updated_at": now,
                },
            )
            self._atomic_write(
                self.followup_path,
                {
                    "command": "open",
                    "session_id": session_id,
                    "timeout_sec": float(followup_timeout_sec),
                    "reason": "manual_interrupt",
                    "generation": generation,
                    "updated_at": now,
                },
            )

    def issue(self, session_id: str = "", followup_timeout_sec: float = 15.0) -> dict[str, Any]:
        """Compatibility helper for callers that do not control robot stop ordering."""
        payload = self.begin(session_id=session_id)
        self.open_listening(payload, followup_timeout_sec=followup_timeout_sec)
        return payload

    def clear_playback_guard(self, command: dict[str, Any], kind: str = "wake_interrupt") -> None:
        with _COMMAND_LOCK:
            generation = int(command.get("generation", -1))
            if generation != self.current_generation():
                raise RuntimeError(
                    f"stale interrupt generation={generation} current={self.current_generation()}"
                )
            now = time.time()
            self._atomic_write(
                self.tts_guard_path,
                {
                    "active": False,
                    "kind": str(kind),
                    "text": "",
                    "session_id": str(command.get("session_id", "")),
                    "ended_at": now,
                    "guard_until": now,
                    "updated_at": now,
                },
            )

    def request_session_end(
        self,
        session_id: str = "",
        user_text: str = "",
        command: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invalidate current work and ask the dialogue node to close the session."""
        payload = command or self.begin(session_id=session_id)
        with _COMMAND_LOCK:
            generation = int(payload.get("generation", -1))
            if generation != self.current_generation():
                raise RuntimeError(
                    f"stale interrupt generation={generation} current={self.current_generation()}"
                )
            session_payload = {
                "command": "end_session",
                "request_id": str(payload.get("request_id", uuid.uuid4().hex)),
                "generation": generation,
                "session_id": str(session_id or payload.get("session_id", "")),
                "user_text": str(user_text),
                "updated_at": time.time(),
            }
            self._atomic_write(self.session_command_path, session_payload)
        return session_payload

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def _atomic_write(self, path: Path, payload: dict[str, Any]) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)
