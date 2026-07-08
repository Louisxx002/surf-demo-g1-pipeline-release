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

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            with patch.object(self.llm_server.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = self.llm_server.post_deepseek_chat_completion({"messages": []})

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
