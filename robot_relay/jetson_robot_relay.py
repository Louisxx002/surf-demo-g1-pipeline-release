#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from typing import Any


HOST = os.environ.get("ROBOT_RELAY_BIND_HOST", os.environ.get("ROBOT_RELAY_HOST", "0.0.0.0"))
PORT = int(os.environ.get("ROBOT_RELAY_PORT", "9999"))
SDK_PATH = os.environ.get("UNITREE_SDK2_PYTHON", "/home/unitree/unitree_sdk2_python")
NETWORK_INTERFACE = os.environ.get("UNITREE_NETWORK_INTERFACE", "eth0")
DOMAIN = int(os.environ.get("UNITREE_DOMAIN_ID", "0"))
VOICE_PEER = os.environ.get("UNITREE_VOICE_PEER", "192.168.123.161")
TIMEOUT = float(os.environ.get("UNITREE_AUDIO_TIMEOUT", "10.0"))

os.environ["CYCLONEDDS_URI"] = (
    "<CycloneDDS><Domain><General>"
    "<AllowMulticast>false</AllowMulticast>"
    f"<NetworkInterfaceAddress>{NETWORK_INTERFACE}</NetworkInterfaceAddress>"
    "</General><Discovery><Peers>"
    f'<Peer address="{VOICE_PEER}"/>'
    "</Peers></Discovery></Domain></CycloneDDS>"
)

sys.path.insert(0, SDK_PATH)

from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # noqa: E402
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient  # noqa: E402


class JetsonRobotRelay:
    def __init__(self) -> None:
        print(f"[relay] init DDS domain={DOMAIN} if={NETWORK_INTERFACE} peer={VOICE_PEER}", flush=True)
        ChannelFactoryInitialize(DOMAIN, NETWORK_INTERFACE)
        self.audio = AudioClient()
        self.audio.SetTimeout(TIMEOUT)
        self.audio.Init()
        code, volume = self.audio.GetVolume()
        print(f"[relay] AudioClient ready code={code} vol={volume}", flush=True)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        command = str(request.get("command", ""))
        started = time.time()
        try:
            if command == "health":
                code, volume = self.audio.GetVolume()
                return self._ok(command, started, audio_code=code, volume=volume)
            if command == "say_text":
                text = str(request.get("text", "")).strip()
                voice = int(request.get("voice", 0))
                if not text:
                    return self._error(command, started, "empty text")
                ret = self.audio.TtsMaker(text, voice)
                return self._ok(command, started, ret=ret)
            if command == "set_light":
                red = int(request.get("red", 0))
                green = int(request.get("green", 0))
                blue = int(request.get("blue", 0))
                ret = self.audio.LedControl(red, green, blue)
                return self._ok(command, started, ret=ret)
            return self._error(command, started, f"unknown command: {command}")
        except Exception as exc:
            return self._error(command, started, repr(exc))

    @staticmethod
    def _ok(command: str, started: float, **fields: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "command": command,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
            **fields,
        }

    @staticmethod
    def _error(command: str, started: float, error: str, **fields: Any) -> dict[str, Any]:
        return {
            "ok": False,
            "command": command,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
            "error": error,
            **fields,
        }


def _handle_conn(relay: JetsonRobotRelay, conn: socket.socket, addr: object) -> None:
    with conn:
        raw = _recv_all(conn)
        try:
            request = json.loads(raw.decode("utf-8"))
            print(f"[relay] recv from {addr}: {request}", flush=True)
            response = relay.handle(request)
        except Exception as exc:
            response = {"ok": False, "command": "unknown", "error": repr(exc)}
        conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


def _recv_all(conn: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def main() -> int:
    relay = JetsonRobotRelay()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        print(f"[relay] listening on {HOST}:{PORT}", flush=True)
        while True:
            conn, addr = server.accept()
            threading.Thread(target=_handle_conn, args=(relay, conn, addr), daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(main())

