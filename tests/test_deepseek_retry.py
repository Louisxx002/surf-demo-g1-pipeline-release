import asyncio
import importlib
import json
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class DeepSeekRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("llm_server", None)
        cls.llm_server = importlib.import_module("llm_server")

    def test_deepseek_retries_transient_url_error_once(self):
        calls = {"count": 0}

        def fake_urlopen(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise urllib.error.URLError(TimeoutError("temporary ssl timeout"))
            return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        env = {
            "OPENAI_API_KEY": "test-key",
            "LLM_DEEPSEEK_RETRY_DELAY_SEC": "0",
            "LLM_DEEPSEEK_REQUEST_TIMEOUT_SEC": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(self.llm_server.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = self.llm_server.post_deepseek_chat_completion({"messages": []})

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(calls["count"], 2)

    def test_deepseek_proxy_prefers_explicit_env(self):
        env = {
            "LLM_DEEPSEEK_PROXY": "http://127.0.0.1:7890",
            "HTTPS_PROXY": "http://other-proxy:7890",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.llm_server._deepseek_proxy(), "http://127.0.0.1:7890")

    def test_infer_returns_fallback_when_deepseek_times_out(self):
        original_backend = self.llm_server.CONFIG.reply_backend
        object.__setattr__(self.llm_server.CONFIG, "reply_backend", "deepseek")

        async def fake_tts(text, lang):
            return None

        try:
            with patch.object(self.llm_server, "infer_deepseek_with_memory", side_effect=RuntimeError("network timeout")):
                with patch.object(self.llm_server, "tts", side_effect=fake_tts):
                    result = asyncio.run(self.llm_server.infer(text="介绍一下西浦", session_id="test"))
        finally:
            object.__setattr__(self.llm_server.CONFIG, "reply_backend", original_backend)

        self.assertTrue(result["fallback"])
        self.assertIn("没连上语言模型", result["reply"])
        self.assertIn("network timeout", result["llm_error"])
        self.assertGreaterEqual(result["timing"]["llm_sec"], 0)
        self.assertTrue(result["tts_ok"])

    def test_infer_returns_reply_when_tts_fails(self):
        original_backend = self.llm_server.CONFIG.reply_backend
        object.__setattr__(self.llm_server.CONFIG, "reply_backend", "deepseek")

        async def fake_tts(text, lang):
            raise RuntimeError("edge tts down")

        try:
            with patch.object(self.llm_server, "infer_deepseek_with_memory", return_value="你好呀"):
                with patch.object(self.llm_server, "tts", side_effect=fake_tts):
                    result = asyncio.run(self.llm_server.infer(text="你好", session_id="test"))
        finally:
            object.__setattr__(self.llm_server.CONFIG, "reply_backend", original_backend)

        self.assertEqual(result["reply"], "你好呀")
        self.assertFalse(result["tts_ok"])
        self.assertIn("edge tts down", result["tts_error"])


if __name__ == "__main__":
    unittest.main()
