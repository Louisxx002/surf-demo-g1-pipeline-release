#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time

from unitree_sdk2py.g1.arm.g1_arm_action_client import action_map


ACTION_ID_TO_NAME = {action_id: name for name, action_id in action_map.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one official Unitree G1 arm action by action id.")
    parser.add_argument("--network", required=True, help="DDS network interface, e.g. eth1.")
    parser.add_argument("--id", required=True, type=int, help="Official G1 arm action id.")
    parser.add_argument("--timeout", default=10.0, type=float, help="Unitree RPC timeout in seconds.")
    parser.add_argument(
        "--release_after_sec",
        default=0.0,
        type=float,
        help="Optionally run release arm after this many seconds.",
    )
    parser.add_argument("--list-actions", action="store_true", help="Print supported actions and exit.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.list_actions:
        for action_id, name in sorted(ACTION_ID_TO_NAME.items()):
            print(f"{action_id}: {name}")
        return 0

    action_name = ACTION_ID_TO_NAME.get(args.id)
    if action_name is None:
        print(f"g1_arm_action failed: unknown action id={args.id}", file=sys.stderr)
        return 2

    if os.environ.get("UNITREE_BACKEND", "direct").strip().lower() == "relay":
        return _run_via_relay(args, action_name)

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient

    print(f"g1_arm_action start network={args.network} id={args.id} name={action_name}", flush=True)
    ChannelFactoryInitialize(0, args.network)
    client = G1ArmActionClient()
    client.SetTimeout(float(args.timeout))
    client.Init()

    ret = client.ExecuteAction(args.id)
    print(f"g1_arm_action executed id={args.id} name={action_name} ret={ret}", flush=True)
    if ret != 0:
        return 3

    if args.release_after_sec > 0 and args.id != action_map["release arm"]:
        time.sleep(args.release_after_sec)
        release_id = action_map["release arm"]
        release_ret = client.ExecuteAction(release_id)
        print(f"g1_arm_action release id={release_id} ret={release_ret}", flush=True)
        if release_ret != 0:
            return 4

    return 0


def _run_via_relay(args: argparse.Namespace, action_name: str) -> int:
    from robot_relay.robot_relay_client import RobotRelayClient, RobotRelayError

    host = os.environ.get("ROBOT_RELAY_HOST", "192.168.123.164")
    port = int(os.environ.get("ROBOT_RELAY_PORT", "9999"))
    timeout = float(os.environ.get("ROBOT_RELAY_TIMEOUT_SEC", str(args.timeout)))
    client = RobotRelayClient(host, port, timeout_sec=timeout)

    print(
        f"g1_arm_action relay start endpoint={host}:{port} id={args.id} name={action_name}",
        flush=True,
    )
    try:
        response = client.run_arm_action(args.id, release_after_sec=args.release_after_sec)
    except RobotRelayError as exc:
        print(f"g1_arm_action relay failed: {exc}", file=sys.stderr, flush=True)
        return 3

    ret = int(response.get("ret", -1))
    print(f"g1_arm_action relay response={response}", flush=True)
    return 0 if ret == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
