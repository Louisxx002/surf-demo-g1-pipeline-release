#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SDK_PYTHON_PATH = PROJECT_ROOT / "deps" / "qwen_ros_node_edg_tts" / "third_party" / "unitree_sdk2_python"


def _bool_arg(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_unitree_sdk() -> None:
    if not SDK_PYTHON_PATH.exists():
        raise RuntimeError(f"Unitree Python SDK path not found: {SDK_PYTHON_PATH}")
    sys.path.insert(0, str(SDK_PYTHON_PATH))


def _check_mode(msc) -> tuple[int, dict]:
    code, data = msc.CheckMode()
    return code, data or {}


def _print_mode(label: str, msc) -> tuple[int, dict]:
    code, data = _check_mode(msc)
    print(f"{label}: code={code} form={data.get('form', '')!r} name={data.get('name', '')!r}", flush=True)
    return code, data


def _print_sport_services(rsc) -> None:
    try:
        code, services = rsc.ServiceList()
    except Exception as exc:
        print(f"service list failed: {exc!r}", flush=True)
        return
    print(f"service list code={code}", flush=True)
    if not services:
        return
    for service in services:
        if "sport" in service.name or "motion" in service.name:
            print(
                f"service name={service.name} status={service.status} protect={service.protect}",
                flush=True,
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore Unitree G1 motion mode back to ai_sport after debug/manual mode tests."
    )
    parser.add_argument(
        "--network_interface",
        default=os.environ.get("UNITREE_NETWORK_INTERFACE", "enp8s0"),
        help="DDS network interface, e.g. enp8s0 or eth1.",
    )
    parser.add_argument(
        "--domain",
        type=int,
        default=int(os.environ.get("UNITREE_DOMAIN_ID", "0") or "0"),
        help="DDS domain id. Defaults to UNITREE_DOMAIN_ID or 0.",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--wait_sec", type=float, default=1.0)
    parser.add_argument(
        "--release_first",
        default=os.environ.get("RESTORE_AI_RELEASE_FIRST", "1"),
        help="Release current non-ai motion mode before selecting ai_sport.",
    )
    parser.add_argument(
        "--service_switch_fallback",
        default=os.environ.get("RESTORE_AI_SERVICE_SWITCH_FALLBACK", "1"),
        help="If SelectMode(ai_sport) fails, try robot_state ServiceSwitch(ai_sport, True).",
    )
    args = parser.parse_args()

    _load_unitree_sdk()
    from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.go2.robot_state.robot_state_client import RobotStateClient

    print(
        f"restore ai_sport start interface={args.network_interface} domain={args.domain}",
        flush=True,
    )
    ChannelFactoryInitialize(args.domain, args.network_interface)

    msc = MotionSwitcherClient()
    msc.SetTimeout(args.timeout)
    msc.Init()

    rsc = RobotStateClient()
    rsc.SetTimeout(args.timeout)
    rsc.Init()

    _, before = _print_mode("before", msc)
    if before.get("name") == "ai":
        print("already in ai_sport mode", flush=True)
        _print_sport_services(rsc)
        return 0

    if _bool_arg(str(args.release_first)) and before.get("name"):
        try:
            ret = msc.ReleaseMode()
        except Exception as exc:
            print(f"release current mode failed: {exc!r}", flush=True)
        else:
            print(f"release current mode ret={ret}", flush=True)
        time.sleep(max(0.0, args.wait_sec))
        _print_mode("after_release", msc)

    try:
        ret = msc.SelectMode("ai_sport")
    except Exception as exc:
        print(f"select ai_sport failed: {exc!r}", flush=True)
        ret = -1
    else:
        print(f"select ai_sport ret={ret}", flush=True)
    time.sleep(max(0.0, args.wait_sec))

    _, after_select = _print_mode("after_select", msc)
    if after_select.get("name") == "ai":
        print("restore ai_sport ok", flush=True)
        _print_sport_services(rsc)
        return 0

    if _bool_arg(str(args.service_switch_fallback)):
        try:
            code = rsc.ServiceSwitch("ai_sport", True)
        except Exception as exc:
            print(f"ServiceSwitch(ai_sport, True) failed: {exc!r}", flush=True)
        else:
            print(f"ServiceSwitch(ai_sport, True) code={code}", flush=True)
        time.sleep(max(0.0, args.wait_sec))
        _, after_switch = _print_mode("after_service_switch", msc)
        if after_switch.get("name") == "ai":
            print("restore ai_sport ok via service switch", flush=True)
            _print_sport_services(rsc)
            return 0

    print("restore ai_sport failed: motion mode is not ai", flush=True)
    _print_sport_services(rsc)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
