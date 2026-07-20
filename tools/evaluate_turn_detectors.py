from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from turn_detection.baseline_detector import BaselineDetector
from turn_detection.dynamic_detector import DynamicV1Detector
from turn_detection.metrics import summarize_comparison
from turn_detection.replay import load_timeline, replay_detector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a JSONL timeline against baseline and dynamic_v1."
    )
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--baseline-silence-ms", type=float, default=600)
    parser.add_argument("--dynamic-silence-ms", type=float, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    events = load_timeline(args.fixture)
    detector_runs = {
        "baseline": replay_detector(
            events, BaselineDetector(args.baseline_silence_ms)
        ),
        "dynamic_v1": replay_detector(
            events, DynamicV1Detector(args.dynamic_silence_ms)
        ),
    }
    payload = {
        "fixture": str(args.fixture),
        "event_count": len(events),
        "detectors": list(detector_runs),
        "metrics": summarize_comparison(events, detector_runs),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
