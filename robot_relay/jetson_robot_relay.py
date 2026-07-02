#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import base64
import struct
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
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient, action_map  # noqa: E402


ACTION_ID_TO_NAME = {action_id: name for name, action_id in action_map.items()}


class JetsonRobotRelay:
    def __init__(self) -> None:
        print(f"[relay] init DDS domain={DOMAIN} if={NETWORK_INTERFACE} peer={VOICE_PEER}", flush=True)
        ChannelFactoryInitialize(DOMAIN, NETWORK_INTERFACE)
        self.audio = AudioClient()
        self.audio.SetTimeout(TIMEOUT)
        self.audio.Init()
        code, volume = self.audio.GetVolume()
        print(f"[relay] AudioClient ready code={code} vol={volume}", flush=True)
        self.arm_action = G1ArmActionClient()
        self.arm_action.SetTimeout(TIMEOUT)
        self.arm_action.Init()
        print("[relay] G1ArmActionClient ready", flush=True)

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
            if command == "play_wav":
                wav_b64 = str(request.get("wav_b64", ""))
                stream = str(request.get("stream", "tts"))
                if not wav_b64:
                    return self._error(command, started, "missing wav_b64")
                wav_bytes = base64.b64decode(wav_b64.encode("ascii"))
                pcm_bytes, sample_rate, num_channels = _read_wav_pcm(wav_bytes)
                chunks, ret = _play_pcm_stream(self.audio, pcm_bytes, stream)
                return self._ok(
                    command,
                    started,
                    ret=ret,
                    bytes=len(wav_bytes),
                    pcm_bytes=len(pcm_bytes),
                    sample_rate=sample_rate,
                    num_channels=num_channels,
                    chunks=chunks,
                )
            if command == "arm_action":
                action_id = int(request.get("id", -1))
                action_name = ACTION_ID_TO_NAME.get(action_id)
                if action_name is None:
                    return self._error(command, started, f"unknown action id: {action_id}")
                release_after_sec = float(request.get("release_after_sec", 0.0))
                ret = self.arm_action.ExecuteAction(action_id)
                release_ret = None
                if ret == 0 and release_after_sec > 0 and action_id != action_map["release arm"]:
                    time.sleep(release_after_sec)
                    release_ret = self.arm_action.ExecuteAction(action_map["release arm"])
                return self._ok(
                    command,
                    started,
                    ret=ret,
                    action_id=action_id,
                    action_name=action_name,
                    release_ret=release_ret,
                )
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
            print(f"[relay] recv from {addr}: {_summarize_request(request)}", flush=True)
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


def _summarize_request(request: dict[str, Any]) -> dict[str, Any]:
    summary = dict(request)
    wav_b64 = summary.pop("wav_b64", None)
    if wav_b64 is not None:
        summary["wav_b64_len"] = len(str(wav_b64))
    return summary


def _read_wav_pcm(wav_bytes: bytes) -> tuple[bytes, int, int]:
    offset = 0

    def read(fmt: str) -> tuple[Any, ...]:
        nonlocal offset
        size = struct.calcsize(fmt)
        if offset + size > len(wav_bytes):
            raise ValueError("truncated wav")
        values = struct.unpack(fmt, wav_bytes[offset : offset + size])
        offset += size
        return values

    (chunk_id,) = read("<I")
    if chunk_id != 0x46464952:
        raise ValueError("wav chunk id is not RIFF")
    read("<I")
    (format_tag,) = read("<I")
    if format_tag != 0x45564157:
        raise ValueError("wav format is not WAVE")

    sample_rate = 0
    num_channels = 0
    bits_per_sample = 0
    pcm_data = b""

    while offset + 8 <= len(wav_bytes):
        subchunk_id, subchunk_size = read("<II")
        chunk_start = offset
        if subchunk_id == 0x20746D66:
            (audio_format,) = read("<H")
            (num_channels,) = read("<H")
            (sample_rate,) = read("<I")
            read("<I")
            read("<H")
            (bits_per_sample,) = read("<H")
            if audio_format != 1:
                raise ValueError(f"unsupported wav format: {audio_format}")
            if bits_per_sample != 16:
                raise ValueError(f"unsupported wav bit depth: {bits_per_sample}")
        elif subchunk_id == 0x61746164:
            pcm_data = wav_bytes[offset : offset + subchunk_size]
        offset = chunk_start + subchunk_size
        if subchunk_size % 2:
            offset += 1

    if not pcm_data:
        raise ValueError("wav has no data chunk")
    if not sample_rate or not num_channels:
        raise ValueError("wav has no fmt chunk")
    return pcm_data, sample_rate, num_channels


def _play_pcm_stream(audio_client: Any, pcm_data: bytes, stream_name: str, chunk_size: int = 96000) -> tuple[int, int]:
    stream_id = str(int(time.time() * 1000))
    offset = 0
    chunk_index = 0
    last_ret = 0
    while offset < len(pcm_data):
        chunk = pcm_data[offset : offset + chunk_size]
        ret_code, _ = audio_client.PlayStream(stream_name, stream_id, chunk)
        last_ret = ret_code
        if ret_code != 0:
            print(f"[relay] PlayStream failed chunk={chunk_index} ret={ret_code}", flush=True)
            return chunk_index, ret_code
        offset += len(chunk)
        chunk_index += 1
        time.sleep(0.05)
    return chunk_index, last_ret


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
