import json
import tempfile
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline_monitor.server import (
    event_view,
    find_latest_pipeline_log,
    read_existing_events,
)


class PipelineMonitorTests(unittest.TestCase):
    def test_find_latest_pipeline_log_ignores_default_and_manual_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            ignored = logs_dir / "default"
            ignored.mkdir()
            (ignored / "pipeline.log").write_text('{"stage":"asr_result"}\n', encoding="utf-8")

            manual = logs_dir / "manual-relay-test"
            manual.mkdir()
            (manual / "pipeline.log").write_text('{"stage":"tts_play_started"}\n', encoding="utf-8")

            older = logs_dir / "20260703_001000_s001"
            older.mkdir()
            (older / "pipeline.log").write_text('{"stage":"wake"}\n', encoding="utf-8")
            time.sleep(0.01)

            latest = logs_dir / "20260703_001100_s001"
            latest.mkdir()
            (latest / "pipeline.log").write_text('{"stage":"llm_reply"}\n', encoding="utf-8")

            self.assertEqual(find_latest_pipeline_log(logs_dir), latest / "pipeline.log")

    def test_event_view_maps_key_pipeline_events(self):
        asr_event = event_view(
            {
                "time": "2026-07-03T00:35:35.675",
                "elapsed_sec": 4.232,
                "stage": "asr_result",
                "text": "介绍一下西交利物浦大学",
                "speaker": "用户7",
                "session_id": "20260703_003240_s001",
            }
        )
        self.assertEqual(asr_event["kind"], "asr")
        self.assertEqual(asr_event["title"], "ASR")
        self.assertEqual(asr_event["message"], "介绍一下西交利物浦大学")
        self.assertEqual(asr_event["meta"]["speaker"], "用户7")

        action_event = event_view(
            {
                "stage": "action_result",
                "label": "高位挥手",
                "official_name": "high wave",
                "action_id": 26,
                "executed": True,
                "reason": "ok",
            }
        )
        self.assertEqual(action_event["kind"], "action")
        self.assertIn("高位挥手", action_event["message"])
        self.assertTrue(action_event["meta"]["executed"])

    def test_read_existing_events_skips_invalid_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "pipeline.log"
            log_path.write_text(
                "\n".join(
                    [
                        json.dumps({"stage": "wake", "wake_word": "你好小浦"}, ensure_ascii=False),
                        "not json",
                        json.dumps({"stage": "llm_reply", "reply": "我在"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )

            events = read_existing_events(log_path)

            self.assertEqual([event["title"] for event in events], ["WAKE", "LLM"])


if __name__ == "__main__":
    unittest.main()
