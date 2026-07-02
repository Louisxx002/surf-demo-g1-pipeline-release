from pathlib import Path


def test_g1_arm_action_runner_matches_pipeline_contract():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "g1_arm_action_runner.py").read_text(
        encoding="utf-8"
    )

    assert 'parser.add_argument("--network", required=True' in source
    assert 'parser.add_argument("--id", required=True, type=int' in source
    assert "ChannelFactoryInitialize(0, args.network)" in source
    assert "client.ExecuteAction(args.id)" in source


def test_g1_arm_action_runner_is_non_interactive():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "g1_arm_action_runner.py").read_text(
        encoding="utf-8"
    )

    assert "input(" not in source
    assert "ACTION_ID_TO_NAME" in source
