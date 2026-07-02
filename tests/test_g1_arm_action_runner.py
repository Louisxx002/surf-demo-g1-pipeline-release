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


def test_g1_arm_action_runner_supports_relay_backend():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "g1_arm_action_runner.py").read_text(
        encoding="utf-8"
    )

    assert 'os.environ.get("UNITREE_BACKEND", "direct")' in source
    assert "RobotRelayClient" in source
    assert "client.run_arm_action(args.id" in source


def test_g1_arm_action_runner_does_not_import_unitree_sdk_before_relay_branch():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "g1_arm_action_runner.py").read_text(
        encoding="utf-8"
    )
    before_relay_branch = source.split('os.environ.get("UNITREE_BACKEND", "direct")', 1)[0]

    assert "unitree_sdk2py" not in before_relay_branch
    assert "ACTION_NAME_TO_ID" in before_relay_branch
