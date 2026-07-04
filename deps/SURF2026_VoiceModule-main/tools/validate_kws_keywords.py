from __future__ import annotations

import argparse
from pathlib import Path
import sys

from kws_keyword_tools import (
    candidate_xiaopu_keywords,
    load_token_set,
    validate_keyword_lines,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate sherpa-onnx KWS keywords.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "models" / "kws",
    )
    parser.add_argument(
        "--show-candidates",
        action="store_true",
        help="Print recommended Xiaopu wake keyword variants.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tokens_path = args.model_dir / "tokens.txt"
    keywords_path = args.model_dir / "keywords.txt"

    token_set = load_token_set(tokens_path)
    keyword_lines = keywords_path.read_text(encoding="utf-8").splitlines()
    errors = validate_keyword_lines(keyword_lines, token_set)

    if args.show_candidates:
        print("candidate keywords:")
        for line in candidate_xiaopu_keywords():
            print(f"  {line}")
        candidate_errors = validate_keyword_lines(candidate_xiaopu_keywords(), token_set)
        if candidate_errors:
            print("candidate validation errors:", file=sys.stderr)
            for error in candidate_errors:
                print(f"  {error}", file=sys.stderr)
            return 1

    if errors:
        print("keywords validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"keywords ok: {keywords_path}")
    print(f"token count: {len(token_set)}")
    print(f"keyword lines: {sum(1 for line in keyword_lines if line.strip())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

