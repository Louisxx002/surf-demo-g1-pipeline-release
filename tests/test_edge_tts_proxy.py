import importlib
import os
import sys
import unittest
from unittest.mock import patch


class EdgeTtsProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("llm_server", None)
        cls.llm_server = importlib.import_module("llm_server")

    def test_edge_tts_proxy_prefers_explicit_env(self):
        with patch.dict(
            os.environ,
            {
                "EDGE_TTS_PROXY": "http://127.0.0.1:7897",
                "HTTPS_PROXY": "http://other-proxy:7890",
            },
            clear=False,
        ):
            self.assertEqual(
                self.llm_server._edge_tts_proxy(),
                "http://127.0.0.1:7897",
            )

    def test_edge_tts_proxy_falls_back_to_https_proxy(self):
        with patch.dict(
            os.environ,
            {
                "EDGE_TTS_PROXY": "",
                "HTTPS_PROXY": "http://127.0.0.1:7897",
            },
            clear=False,
        ):
            self.assertEqual(
                self.llm_server._edge_tts_proxy(),
                "http://127.0.0.1:7897",
            )


if __name__ == "__main__":
    unittest.main()
