import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline_log.latency_tracker import build_turn_summaries


class LatencyTrackerTests(unittest.TestCase):
    def test_build_turn_summary_for_single_reply_turn(self):
        events = [
            {"time": "2026-07-03T10:00:00.000", "stage": "wake", "wake_word": "你好小浦"},
            {"time": "2026-07-03T10:00:00.100", "stage": "asr_started", "session_id": "s001"},
            {"time": "2026-07-03T10:00:04.900", "stage": "asr_result", "text": "介绍一下西交利物浦大学", "speaker": "用户1", "session_id": "s001"},
            {"time": "2026-07-03T10:00:05.000", "stage": "asr_received", "text": "介绍一下西交利物浦大学", "speaker": "用户1", "session_id": "s001"},
            {"time": "2026-07-03T10:00:10.000", "stage": "llm_reply", "reply": "西交利物浦大学在苏州。", "session_id": "s001"},
            {"time": "2026-07-03T10:00:11.500", "stage": "tts_ready", "text": "西交利物浦大学在苏州。", "session_id": "s001"},
            {"time": "2026-07-03T10:00:11.700", "stage": "action_result", "label": "高位挥手", "action_id": 26, "executed": True, "session_id": "s001"},
            {"time": "2026-07-03T10:00:11.800", "stage": "tts_play_started", "kind": "reply", "text": "西交利物浦大学在苏州。"},
            {"time": "2026-07-03T10:00:18.300", "stage": "tts_play_finished", "kind": "reply", "text": "西交利物浦大学在苏州。"},
        ]

        summaries = build_turn_summaries(events)

        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertEqual(summary["asr_text"], "介绍一下西交利物浦大学")
        self.assertEqual(summary["reply"], "西交利物浦大学在苏州。")
        self.assertEqual(summary["action"]["label"], "高位挥手")
        self.assertEqual(summary["latency_ms"]["asr_record"], 4800)
        self.assertEqual(summary["latency_ms"]["asr_to_llm_reply"], 5000)
        self.assertEqual(summary["latency_ms"]["llm_to_tts_ready"], 1500)
        self.assertEqual(summary["latency_ms"]["tts_play"], 6500)
        self.assertEqual(summary["latency_ms"]["turn_total"], 18200)

    def test_build_turn_summary_splits_followup_turns(self):
        events = [
            {"time": "2026-07-03T10:00:00.000", "stage": "asr_started", "session_id": "s001"},
            {"time": "2026-07-03T10:00:02.000", "stage": "asr_result", "text": "你好", "session_id": "s001"},
            {"time": "2026-07-03T10:00:02.100", "stage": "asr_received", "text": "你好", "session_id": "s001"},
            {"time": "2026-07-03T10:00:04.000", "stage": "llm_reply", "reply": "你好呀", "session_id": "s001"},
            {"time": "2026-07-03T10:00:05.000", "stage": "tts_ready", "text": "你好呀", "session_id": "s001"},
            {"time": "2026-07-03T10:00:05.100", "stage": "tts_play_started", "kind": "reply", "text": "你好呀"},
            {"time": "2026-07-03T10:00:08.000", "stage": "tts_play_finished", "kind": "reply", "text": "你好呀"},
            {"time": "2026-07-03T10:00:12.000", "stage": "followup_asr_started", "session_id": "s001"},
            {"time": "2026-07-03T10:00:15.000", "stage": "asr_result", "text": "再讲一个", "session_id": "s001"},
            {"time": "2026-07-03T10:00:15.100", "stage": "asr_received", "text": "再讲一个", "session_id": "s001"},
            {"time": "2026-07-03T10:00:18.000", "stage": "llm_reply", "reply": "好的", "session_id": "s001"},
            {"time": "2026-07-03T10:00:19.000", "stage": "tts_ready", "text": "好的", "session_id": "s001"},
        ]

        summaries = build_turn_summaries(events)

        self.assertEqual([summary["turn_index"] for summary in summaries], [1, 2])
        self.assertEqual([summary["asr_text"] for summary in summaries], ["你好", "再讲一个"])


if __name__ == "__main__":
    unittest.main()
