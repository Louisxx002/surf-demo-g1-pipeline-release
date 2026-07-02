from __future__ import annotations

import base64
import json
import socket
from pathlib import Path
from typing import Any


class RobotRelayError(RuntimeError):
    """Raised when the Jetson robot relay cannot complete a command."""


class RobotRelayClient:
    def __init__(self, host: str, port: int, timeout_sec: float = 5.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout_sec = float(timeout_sec)

    def health(self) -> dict[str, Any]:
        return self.request({"command": "health"})

    def say_text(self, text: str, voice: int = 0) -> dict[str, Any]:
        return self.request({"command": "say_text", "text": text, "voice": int(voice)})

    def set_light(self, red: int, green: int, blue: int, effect: str = "solid") -> dict[str, Any]:
        return self.request(
            {
                "command": "set_light",
                "red": int(red),
                "green": int(green),
                "blue": int(blue),
                "effect": effect,
            }
        )

    def restore_ai_sport(self, release_first: bool = True, service_switch_fallback: bool = True) -> dict[str, Any]:
        return self.request(
            {
                "command": "restore_ai_sport",
                "release_first": bool(release_first),
                "service_switch_fallback": bool(service_switch_fallback),
            }
        )

    def play_wav(self, path: str, stream: str = "tts") -> dict[str, Any]:
        wav_path = Path(path)
        wav_bytes = wav_path.read_bytes()
        return self.request(
            {
                "command": "play_wav",
                "filename": wav_path.name,
                "stream": stream,
                "wav_b64": base64.b64encode(wav_bytes).decode("ascii"),
            }
        )

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command", "unknown"))
        try:
            with socket.create_connection((self.host, self.port), self.timeout_sec) as sock:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                sock.sendall(raw)
                sock.shutdown(socket.SHUT_WR)
                response = self._recv_all(sock)
        except Exception as exc:
            raise RobotRelayError(
                f"robot relay request failed command={command} endpoint={self.host}:{self.port}: {exc}"
            ) from exc

        try:
            decoded = json.loads(response.decode("utf-8").strip())
        except Exception as exc:
            raise RobotRelayError(
                f"robot relay returned invalid JSON command={command} endpoint={self.host}:{self.port}: {response!r}"
            ) from exc

        if not isinstance(decoded, dict):
            raise RobotRelayError(f"robot relay returned non-object response command={command}: {decoded!r}")
        if not decoded.get("ok", False):
            error = decoded.get("error", "unknown relay error")
            raise RobotRelayError(f"robot relay command failed command={command}: {error}; response={decoded!r}")
        return decoded

    @staticmethod
    def _recv_all(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
