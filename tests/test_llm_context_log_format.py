from pathlib import Path


def test_llm_context_node_has_operator_friendly_log_markers():
    source = (Path(__file__).resolve().parents[1] / "llm_surf_context_node.py").read_text(encoding="utf-8")

    assert "[WAKE]" in source
    assert "[SPEAKER]" in source
    assert "[ASR]" in source
    assert "[LLM]" in source
    assert "[TTS]" in source
    assert "[ACTION]" in source


def test_llm_context_node_logs_disabled_standby_ack():
    source = (Path(__file__).resolve().parents[1] / "llm_surf_context_node.py").read_text(encoding="utf-8")

    assert "[STANDBY] skipped" in source
