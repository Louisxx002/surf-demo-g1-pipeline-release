from __future__ import annotations

import logging
import socket
import struct
import threading

from audio.audio_bus import AudioBus
from config.voice_config import CONFIG

logger = logging.getLogger(__name__)


class RobotMicCapture:
    """从机器人 UDP 组播地址接收降噪后的麦克风音频，推入 AudioBus。

    格式固定：单声道 / 16kHz / 16bit PCM，与 MicCapture 输出相同。
    """

    def __init__(
        self,
        bus: AudioBus,
        group_ip: str = CONFIG.robot_mic_group,
        port: int = CONFIG.robot_mic_port,
        local_if: str = CONFIG.robot_mic_interface,
    ) -> None:
        self._bus = bus
        self._group_ip = group_ip
        self._port = port
        self._local_if = local_if
        self._pending = b""
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._stop_event.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self._port))
        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(self._group_ip),
            socket.inet_aton(self._local_if),
        )
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError as e:
            sock.close()
            raise OSError(
                f"无法加入组播组 {self._group_ip}（本地接口 {self._local_if}）。"
                f"请确认机器人网线已连接且 WSL2 eth1 IP 为 {self._local_if}。"
                f"原始错误：{e}"
            ) from e
        sock.settimeout(1.0)
        self._sock = sock
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        logger.info("RobotMicCapture started: %s:%d", self._group_ip, self._port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._sock:
            self._sock.close()
            self._sock = None

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, _ = self._sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break

            self._pending += data
            while len(self._pending) >= CONFIG.frame_bytes:
                frame = self._pending[: CONFIG.frame_bytes]
                self._pending = self._pending[CONFIG.frame_bytes :]
                self._bus.push(frame)
