import json
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
import sys
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline_monitor.server import (
    event_view,
    find_latest_pipeline_log,
    make_handler,
    pipeline_status,
    read_existing_events,
    run_pipeline_command,
)
from http.server import ThreadingHTTPServer


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

        failed_event = event_view(
            {
                "stage": "llm_failed",
                "error": "HTTPConnectionPool read timed out",
                "timeout_sec": 20,
                "session_id": "s001",
            }
        )
        self.assertEqual(failed_event["kind"], "error")
        self.assertEqual(failed_event["title"], "LLM_FAILED")
        self.assertIn("timed out", failed_event["message"])
        self.assertEqual(failed_event["meta"]["timeout_sec"], 20)

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

    def test_api_events_includes_turn_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            session_dir = logs_dir / "20260703_120000_s001"
            session_dir.mkdir()
            (session_dir / "pipeline.log").write_text(
                "\n".join(
                    [
                        json.dumps({"time": "2026-07-03T12:00:00.000", "stage": "asr_started", "session_id": "s001"}, ensure_ascii=False),
                        json.dumps({"time": "2026-07-03T12:00:02.000", "stage": "asr_result", "text": "你好", "session_id": "s001"}, ensure_ascii=False),
                        json.dumps({"time": "2026-07-03T12:00:02.100", "stage": "asr_received", "text": "你好", "session_id": "s001"}, ensure_ascii=False),
                        json.dumps({"time": "2026-07-03T12:00:04.000", "stage": "llm_reply", "reply": "你好呀", "session_id": "s001"}, ensure_ascii=False),
                    ]
                ),
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(logs_dir))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/api/events?limit=10"
                payload = json.loads(urllib.request.urlopen(url, timeout=3).read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["turn_summaries"][0]["asr_text"], "你好")

    def test_pipeline_status_reports_running_when_core_services_are_active(self):
        def fake_runner(command, **kwargs):
            service = command[-1]
            stdout = "active\n" if service in {"surf-voice-runtime", "surf-llm-node", "surf-llm-audio-player"} else "inactive\n"
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

        def fake_relay_checker():
            return {"ready": True, "state": "ready", "endpoint": "192.168.123.164:9999"}

        status = pipeline_status(command_runner=fake_runner, relay_checker=fake_relay_checker)

        self.assertEqual(status["state"], "running")
        self.assertTrue(status["services"]["surf-voice-runtime"]["active"])
        self.assertTrue(status["components"]["robot_relay"]["ready"])

    def test_pipeline_status_reports_partial_when_robot_relay_is_not_ready(self):
        def fake_runner(command, **kwargs):
            return type("Result", (), {"returncode": 0, "stdout": "active\n", "stderr": ""})()

        def fake_relay_checker():
            return {
                "ready": False,
                "state": "not_ready",
                "endpoint": "192.168.123.164:9999",
                "hint": "cd ~/surf_robot_relay && ./scripts/run_jetson_robot_relay.sh",
            }

        status = pipeline_status(command_runner=fake_runner, relay_checker=fake_relay_checker)

        self.assertEqual(status["state"], "partial")
        self.assertFalse(status["components"]["robot_relay"]["ready"])
        self.assertIn("run_jetson_robot_relay", status["components"]["robot_relay"]["hint"])

    def test_run_pipeline_command_builds_safe_start_environment(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "started", "stderr": ""})()

        result = run_pipeline_command("start", command_runner=fake_runner)

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], ["./scripts/run_pipeline.sh", "--mode", "wake"])
        env = calls[0][1]["env"]
        self.assertEqual(env["UNITREE_BACKEND"], "relay")
        self.assertEqual(env["ROBOT_RELAY_HOST"], "192.168.123.164")
        self.assertEqual(env["SURF_LLM_WAKE_LISTEN_SEC"], "15")
        self.assertEqual(env["LLM_FOLLOWUP_TIMEOUT_SEC"], "15")
        self.assertEqual(env["LLM_REQUEST_TIMEOUT_SEC"], "20")

    def test_event_view_maps_session_state_events(self):
        event = event_view(
            {
                "stage": "terminate_command",
                "session_id": "20260704_120000_s001",
            }
        )

        self.assertEqual(event["kind"], "state")
        self.assertEqual(event["title"], "SESSION")
        self.assertIn("关闭", event["message"])
        self.assertEqual(event["meta"]["session_id"], "20260704_120000_s001")

    def test_run_pipeline_command_rejects_unknown_action(self):
        with self.assertRaises(ValueError):
            run_pipeline_command("restart")


if __name__ == "__main__":
    unittest.main()
