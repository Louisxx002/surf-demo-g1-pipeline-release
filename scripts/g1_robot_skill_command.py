#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCO_CLIENT = (
    PROJECT_ROOT
    / "deps"
    / "unitree_g1_action_classifier_package"
    / "unitree_sdk2"
    / "build"
    / "bin"
    / "g1_loco_client"
)

MAX_VX = 0.2
MAX_VY = 0.1
MAX_YAW = 0.4
MAX_DURATION = 0.8

COMMANDS: dict[str, dict[str, float | str]] = {
    "forward_step": {"vx": 0.15, "vy": 0.0, "yaw": 0.0, "duration": 0.6},
    "backward_step": {"vx": -0.12, "vy": 0.0, "yaw": 0.0, "duration": 0.6},
    "turn_left": {"vx": 0.0, "vy": 0.0, "yaw": 0.35, "duration": 0.5},
    "turn_right": {"vx": 0.0, "vy": 0.0, "yaw": -0.35, "duration": 0.5},
    "stop": {"api": "stop_move"},
    "squat": {"api": "squat"},
    "lie_down": {"api": "dry_run_only"},
    "stand_up": {"api": "stand_up"},
    "sing": {"api": "dry_run_only"},
}


def _bool_arg(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def _safe_motion_params(spec: dict[str, float | str]) -> tuple[float, float, float, float]:
    vx = _clamp(float(spec.get("vx", 0.0)), MAX_VX)
    vy = _clamp(float(spec.get("vy", 0.0)), MAX_VY)
    yaw = _clamp(float(spec.get("yaw", 0.0)), MAX_YAW)
    duration = max(0.0, min(float(spec.get("duration", 0.0)), MAX_DURATION))
    return vx, vy, yaw, duration


def _run_loco(loco_client: Path, network_interface: str, *args: str) -> None:
    cmd = [str(loco_client), f"--network_interface={network_interface}", *args]
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe G1 robot skill command wrapper.")
    parser.add_argument("--command", required=True, choices=sorted(COMMANDS))
    parser.add_argument("--network_interface", default=os.environ.get("UNITREE_NETWORK_INTERFACE", "enp8s0"))
    parser.add_argument("--execute", default=os.environ.get("LLM_ROBOT_SKILL_EXECUTE", "0"))
    parser.add_argument("--loco_client", default=str(DEFAULT_LOCO_CLIENT))
    args = parser.parse_args()

    execute = _bool_arg(str(args.execute))
    command = args.command
    spec = COMMANDS[command]
    loco_client = Path(args.loco_client)

    if all(key in spec for key in ("vx", "vy", "yaw", "duration")):
        vx, vy, yaw, duration = _safe_motion_params(spec)
        print(
            "robot_skill dry-run "
            f"command={command} vx={vx:.3f} vy={vy:.3f} yaw={yaw:.3f} duration={duration:.3f}",
            flush=True,
        )
        if not execute:
            return 0
        if not loco_client.exists():
            print(f"robot_skill failed command={command} error=loco_client_not_found path={loco_client}", file=sys.stderr)
            return 2
        try:
            _run_loco(
                loco_client,
                args.network_interface,
                f"--set_velocity={vx:.3f} {vy:.3f} {yaw:.3f} {duration:.3f}",
            )
        finally:
            _run_loco(loco_client, args.network_interface, "--stop_move")
        print(f"robot_skill executed command={command}", flush=True)
        return 0

    api = str(spec.get("api", "dry_run_only"))
    print(f"robot_skill dry-run command={command} api={api}", flush=True)
    if not execute:
        return 0
    if api == "dry_run_only":
        print(f"robot_skill skipped command={command} reason=dry_run_only_api", flush=True)
        return 0
    if not loco_client.exists():
        print(f"robot_skill failed command={command} error=loco_client_not_found path={loco_client}", file=sys.stderr)
        return 2
    _run_loco(loco_client, args.network_interface, f"--{api}")
    if command in {"squat", "stand_up"}:
        _run_loco(loco_client, args.network_interface, "--stop_move")
    print(f"robot_skill executed command={command}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
