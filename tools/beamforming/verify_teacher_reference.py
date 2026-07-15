from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from beamforming.reference_verification import verify_teacher_reference  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the Python fixed beamformer against the teacher MATLAB output."
    )
    parser.add_argument("reference_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = verify_teacher_reference(args.reference_dir, output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
