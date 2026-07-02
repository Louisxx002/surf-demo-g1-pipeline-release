import json
import socket

import pytest

from robot_relay.robot_relay_client import RobotRelayClient, RobotRelayError


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.sent = b""
        self.shutdown_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def sendall(self, data):
        self.sent += data

    def shutdown(self, how):
        assert how == socket.SHUT_WR
        self.shutdown_called = True

    def recv(self, _size):
        chunk = self.response
        self.response = b""
        return chunk


def test_health_serializes_json_and_parses_response(monkeypatch):
    fake = FakeSocket(b'{"ok":true,"command":"health","audio_code":0}\n')
    calls = []

    def fake_create_connection(address, timeout):
        calls.append((address, timeout))
        return fake

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    client = RobotRelayClient("192.168.123.164", 9999, timeout_sec=2.5)
    response = client.health()

    assert calls == [(("192.168.123.164", 9999), 2.5)]
    assert json.loads(fake.sent.decode("utf-8")) == {"command": "health"}
    assert fake.shutdown_called
    assert response["audio_code"] == 0


def test_say_text_preserves_chinese_text(monkeypatch):
    fake = FakeSocket(b'{"ok":true,"command":"say_text","ret":0}\n')
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: fake)

    client = RobotRelayClient("robot.local", 9999)
    response = client.say_text("\u6211\u5728", voice=1)

    assert json.loads(fake.sent.decode("utf-8")) == {
        "command": "say_text",
        "text": "\u6211\u5728",
        "voice": 1,
    }
    assert response["ret"] == 0


def test_non_ok_response_raises_clear_error(monkeypatch):
    fake = FakeSocket(b'{"ok":false,"command":"say_text","error":"AudioClient not ready","code":3102}\n')
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: fake)

    client = RobotRelayClient("robot.local", 9999)

    with pytest.raises(RobotRelayError, match="AudioClient not ready"):
        client.say_text("\u4f60\u597d")


def test_connection_failure_raises_clear_error(monkeypatch):
    def fail_connect(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", fail_connect)

    client = RobotRelayClient("robot.local", 9999, timeout_sec=0.1)

    with pytest.raises(RobotRelayError, match="robot.local:9999"):
        client.health()
