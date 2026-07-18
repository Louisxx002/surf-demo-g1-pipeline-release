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
    PIPELINE_ENV_DEFAULTS,
    detect_robot_mic_device,
    event_view,
    ensure_robot_runtime,
    find_latest_pipeline_log,
    make_handler,
    pipeline_status,
    read_existing_events,
    robot_mic_status,
    run_pipeline_command,
    run_pipeline_interrupt,
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

        interrupted_event = event_view(
            {
                "stage": "manual_interrupt",
                "generation": 8,
                "listening_opened": False,
                "partial": True,
                "errors": ["stop_audio returned ret=3102"],
            }
        )
        self.assertEqual(interrupted_event["kind"], "error")
        self.assertEqual(interrupted_event["title"], "INTERRUPT_FAILED")
        self.assertEqual(interrupted_event["message"], "打断未完成")
        self.assertFalse(interrupted_event["meta"]["listening_opened"])

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

        def fake_mic_checker():
            return {
                "ready": True,
                "state": "ready",
                "endpoint": "192.168.123.225:5556",
                "processing_mode": "mean4",
                "source_channels": "8",
                "channel_map": "0,1,2,3",
            }

        status = pipeline_status(
            command_runner=fake_runner,
            relay_checker=fake_relay_checker,
            mic_checker=fake_mic_checker,
        )

        self.assertEqual(status["state"], "running")
        self.assertTrue(status["services"]["surf-voice-runtime"]["active"])
        self.assertTrue(status["components"]["robot_relay"]["ready"])
        self.assertTrue(status["components"]["robot_mic"]["ready"])
        self.assertEqual(
            status["components"]["robot_mic"]["detail"],
            "mean4 | 8ch | channels 0,1,2,3",
        )

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

        status = pipeline_status(
            command_runner=fake_runner,
            relay_checker=fake_relay_checker,
            mic_checker=lambda: {"ready": True, "state": "ready", "endpoint": "192.168.123.225:5556"},
        )

        self.assertEqual(status["state"], "partial")
        self.assertFalse(status["components"]["robot_relay"]["ready"])
        self.assertIn("run_jetson_robot_relay", status["components"]["robot_relay"]["hint"])

    def test_run_pipeline_command_builds_safe_start_environment(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "started", "stderr": ""})()

        result = run_pipeline_command(
            "start",
            command_runner=fake_runner,
            robot_runtime_starter=lambda: {"ok": True, "relay_ready": True, "mic_ready": True},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0], ["./scripts/run_pipeline.sh", "--mode", "wake"])
        env = calls[0][1]["env"]
        self.assertEqual(env["UNITREE_BACKEND"], "relay")
        self.assertEqual(env["VOICE_AUDIO_SOURCE"], "robot")
        self.assertEqual(env["VOICE_ROBOT_MIC_IF"], "192.168.123.225")
        self.assertEqual(env["VOICE_ROBOT_MIC_PORT"], "5556")
        self.assertEqual(env["ROBOT_RELAY_HOST"], "192.168.123.164")
        self.assertEqual(env["SURF_LLM_WAKE_LISTEN_SEC"], "15")
        self.assertEqual(env["LLM_FOLLOWUP_TIMEOUT_SEC"], "15")
        self.assertEqual(env["LLM_REQUEST_TIMEOUT_SEC"], "20")
        self.assertEqual(PIPELINE_ENV_DEFAULTS["ROBOT_MIC_PROCESSING_MODE"], "mean4")
        self.assertEqual(PIPELINE_ENV_DEFAULTS["ROBOT_MIC_SOURCE_CHANNELS"], "8")
        self.assertEqual(PIPELINE_ENV_DEFAULTS["ROBOT_MIC_CHANNEL_MAP"], "0,1,2,3")

    def test_pipeline_defaults_never_fall_back_to_local_or_direct(self):
        self.assertEqual(PIPELINE_ENV_DEFAULTS["UNITREE_BACKEND"], "relay")
        self.assertEqual(PIPELINE_ENV_DEFAULTS["VOICE_AUDIO_SOURCE"], "robot")

    def test_detect_robot_mic_device_tracks_alsa_card_number(self):
        arecord_output = """\
card 0: Dongle [Bothlent UAC Dongle], device 0: USB Audio [USB Audio]
card 2: APE [NVIDIA Jetson Orin NX APE], device 0: tegra-dlink-0 []
"""

        self.assertEqual(detect_robot_mic_device(arecord_output), "hw:0,0")

    def test_robot_mic_status_uses_dedicated_ssh_key_and_process_probe(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "arecord -l":
                return type(
                    "Result",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "card 0: Dongle [Bothlent UAC Dongle], device 0: USB Audio [USB Audio]\n",
                        "stderr": "",
                    },
                )()
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": (
                        "123 python3 /home/unitree/surf_robot_mic/tools/stream_usb_mic.py "
                        "--device hw:0,0 --port 5556 --mode mean4 --channels 8 "
                        "--channel-map 0,1,2,3\n"
                    ),
                    "stderr": "",
                },
            )()

        status = robot_mic_status(command_runner=fake_runner)

        self.assertTrue(status["ready"])
        self.assertIn("surf_robot_ed25519", " ".join(calls[0][0]))
        self.assertIn("BatchMode=yes", " ".join(calls[0][0]))
        self.assertEqual(calls[0][0][-1], "arecord -l")
        self.assertIn("tream_usb_mic.py", calls[1][0][-1])
        self.assertIn("--device hw:0,0", calls[1][0][-1])
        self.assertIn("--mode mean4", calls[1][0][-1])
        self.assertIn("--channels 8", calls[1][0][-1])
        self.assertIn("--channel-map 0,1,2,3", calls[1][0][-1])
        self.assertEqual(status["processing_mode"], "mean4")

    def test_ensure_robot_runtime_starts_relay_and_external_mic(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "arecord -l":
                return type(
                    "Result",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "card 0: Dongle [Bothlent UAC Dongle], device 0: USB Audio [USB Audio]\n",
                        "stderr": "",
                    },
                )()
            if command[-1].startswith("test -r "):
                return type("Result", (), {"returncode": 0, "stdout": "runtime-ready\n", "stderr": ""})()
            if command[-1].startswith("pgrep -af"):
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "robot-runtime-ready\n", "stderr": ""})()

        result = ensure_robot_runtime(
            command_runner=fake_runner,
            relay_checker=lambda: {"ready": True},
            mic_checker=lambda: {"ready": True},
            sleep=lambda _: None,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0][-1], "arecord -l")
        runtime_probe = calls[1][0][-1]
        self.assertIn("/home/unitree/surf_robot_mic/tools/stream_usb_mic.py", runtime_probe)

        cleanup_command = calls[2][0][-1]
        self.assertIn("pkill -f", cleanup_command)
        self.assertNotIn("nohup python3", cleanup_command)

        probe_command = calls[3][0][-1]
        self.assertIn("pgrep -af", probe_command)
        self.assertIn("--device hw:0,0", probe_command)

        start_command = calls[4][0][-1]
        self.assertIn("run_jetson_robot_relay.sh", start_command)
        self.assertIn("stream_usb_mic.py", start_command)
        self.assertIn("hw:0,0", start_command)
        self.assertIn("setsid -f", start_command)
        self.assertNotIn("nohup", start_command)
        self.assertNotIn("pkill -f", start_command)
        self.assertIn("--device hw:0,0.*--port 5556", cleanup_command)
        self.assertIn("192.168.123.225", start_command)
        self.assertIn("5556", start_command)
        self.assertIn("--mode mean4", start_command)
        self.assertIn("--channels 8", start_command)
        self.assertIn("--channel-map 0,1,2,3", start_command)
        self.assertIn(
            "setsid -f env PYTHONPATH=/home/unitree/surf_robot_mic /usr/bin/python3",
            start_command,
        )
        self.assertNotIn("setsid -f PYTHONPATH=", start_command)
        self.assertIn("/usr/bin/python3", start_command)
        self.assertNotIn("~/Desktop/stream_usb_mic.py", start_command)

    def test_ensure_robot_runtime_refuses_to_fall_back_when_new_mic_runtime_is_missing(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "arecord -l":
                return type(
                    "Result",
                    (),
                    {
                        "returncode": 0,
                        "stdout": "card 2: Dongle [Bothlent UAC Dongle], device 0: USB Audio [USB Audio]\n",
                        "stderr": "",
                    },
                )()
            return type(
                "Result",
                (),
                {"returncode": 1, "stdout": "", "stderr": "missing runtime"},
            )()

        result = ensure_robot_runtime(command_runner=fake_runner)

        self.assertFalse(result["ok"])
        self.assertIn("deploy_robot_mic_runtime.sh", result["error"])
        self.assertEqual(len(calls), 2)

    def test_start_does_not_launch_local_pipeline_when_robot_runtime_is_unavailable(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return type("Result", (), {"returncode": 0, "stdout": "started", "stderr": ""})()

        result = run_pipeline_command(
            "start",
            command_runner=fake_runner,
            robot_runtime_starter=lambda: {"ok": False, "error": "ssh key not installed"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])
        self.assertIn("ssh key", result["error"])

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

    def test_run_pipeline_interrupt_stops_audio_releases_arm_and_records_event(self):
        calls = []

        class FakeRelayClient:
            def stop_audio(self, app_name, generation=None):
                calls.append(("stop_audio", app_name, generation))
                return {"ok": True, "ret": 0}

            def release_arm(self, generation=None):
                calls.append(("release_arm", generation))
                return {"ok": True, "ret": 0}

        class FakeControl:
            def begin(self, session_id):
                calls.append(("begin", session_id))
                return {"request_id": "interrupt-1", "generation": 4, "session_id": session_id}

            def open_listening(self, command, followup_timeout_sec):
                calls.append(("open_listening", command["generation"], followup_timeout_sec))

        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp) / "logs"
            log_path = logs_dir / "20260718_010203_s001" / "pipeline.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text('{"stage":"llm_reply"}\n', encoding="utf-8")

            result = run_pipeline_interrupt(
                logs_dir=logs_dir,
                pipeline_running_checker=lambda: True,
                relay_client_factory=lambda: FakeRelayClient(),
                interrupt_control=FakeControl(),
                followup_timeout_sec=15,
            )

            self.assertTrue(result["ok"])
            self.assertFalse(result["partial"])
            self.assertEqual(result["generation"], 4)
            self.assertEqual(
                calls,
                [
                    ("begin", "20260718_010203_s001"),
                    ("stop_audio", "tts", 4),
                    ("release_arm", 4),
                    ("open_listening", 4, 15),
                ],
            )
            event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(event["stage"], "manual_interrupt")
            self.assertEqual(event["generation"], 4)

    def test_run_pipeline_interrupt_refuses_when_pipeline_is_stopped(self):
        result = run_pipeline_interrupt(
            pipeline_running_checker=lambda: False,
            relay_client_factory=lambda: self.fail("relay must not be called"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "pipeline_not_running")

    def test_run_pipeline_interrupt_reports_nonzero_robot_results_as_partial(self):
        class FakeRelayClient:
            def stop_audio(self, app_name, generation=None):
                return {"ok": True, "ret": 3102, "app_name": app_name}

            def release_arm(self, generation=None):
                return {"ok": True, "ret": 3102, "action_id": 99}

        class FakeControl:
            def begin(self, session_id):
                return {"request_id": "interrupt-2", "generation": 5, "session_id": session_id}

            def open_listening(self, command, followup_timeout_sec):
                self.opened = True

        result = run_pipeline_interrupt(
            pipeline_running_checker=lambda: True,
            relay_client_factory=lambda: FakeRelayClient(),
            interrupt_control=FakeControl(),
            followup_timeout_sec=15,
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["partial"])
        self.assertIn("stop_audio returned ret=3102", result["errors"])
        self.assertIn("release_arm returned ret=3102", result["errors"])
        self.assertFalse(result["listening_opened"])

    def test_run_pipeline_interrupt_does_not_listen_when_arm_release_fails(self):
        class FakeRelayClient:
            def stop_audio(self, app_name, generation=None):
                return {"ok": True, "ret": 0, "app_name": app_name}

            def release_arm(self, generation=None):
                return {"ok": True, "ret": 3102, "action_id": 99}

        class FakeControl:
            opened = False

            def begin(self, session_id):
                return {"request_id": "interrupt-3", "generation": 6, "session_id": session_id}

            def open_listening(self, command, followup_timeout_sec):
                self.opened = True

        control = FakeControl()
        result = run_pipeline_interrupt(
            pipeline_running_checker=lambda: True,
            relay_client_factory=lambda: FakeRelayClient(),
            interrupt_control=control,
            followup_timeout_sec=15,
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["listening_opened"])
        self.assertFalse(control.opened)
        self.assertIn("动作未安全释放", result["message"])

    def test_monitor_ui_exposes_manual_interrupt_control(self):
        project_root = Path(__file__).resolve().parents[1]
        html = (project_root / "ui/pipeline_monitor/index.html").read_text(encoding="utf-8")
        javascript = (project_root / "ui/pipeline_monitor/app.js").read_text(encoding="utf-8")

        self.assertIn('id="interruptPipelineButton"', html)
        self.assertIn("打断并听取", html)
        self.assertIn('fetch("/api/pipeline/interrupt"', javascript)
        self.assertIn('interruptPipelineButton.disabled = state !== "running"', javascript)
        self.assertIn('setSessionStatus("打断失败", "partial")', javascript)
        self.assertIn('let currentLogPath = "";', javascript)
        self.assertIn("switchLogIfNeeded(payload.log_path)", javascript)
        self.assertIn("resetMonitorData", javascript)
        interrupt_handler = javascript.split("async function runPipelineInterrupt()", 1)[1].split(
            "function compactCommandOutput", 1
        )[0]
        self.assertNotIn("addEvent({", interrupt_handler.split("catch (error)", 1)[0])


if __name__ == "__main__":
    unittest.main()
