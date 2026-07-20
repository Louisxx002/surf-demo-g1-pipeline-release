import unittest
from pathlib import Path


class WakeInterruptContractTests(unittest.TestCase):
    def test_wake_handler_interrupts_active_playback_before_acknowledging(self):
        source = (
            Path(__file__).resolve().parents[1] / "llm_surf_context_node.py"
        ).read_text(encoding="utf-8")
        handler = source.split("    def on_wake(", 1)[1].split("    def on_vad(", 1)[0]

        interrupt_index = handler.index("_interrupt_active_reply_for_wake")
        acknowledgement_index = handler.index("_maybe_play_wake_ack")

        self.assertLess(interrupt_index, acknowledgement_index)

    def test_node_polls_ui_session_end_commands(self):
        source = (
            Path(__file__).resolve().parents[1] / "llm_surf_context_node.py"
        ).read_text(encoding="utf-8")

        self.assertIn("self.create_timer(0.2, self._poll_session_command)", source)
        self.assertIn('command.get("command") != "end_session"', source)
        self.assertIn("self._handle_terminate_command", source)


if __name__ == "__main__":
    unittest.main()
