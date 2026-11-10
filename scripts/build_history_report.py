"""Build a standalone history heatmap from phase JSONL in chronological context groups."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.history import write_history_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-runs", type=int, default=10)
    parser.add_argument("--min-switches", type=int, default=3)
    args = parser.parse_args()
    try:
        history = write_history_report(args.inputs, args.output, min_runs=args.min_runs,
                                       min_switches=args.min_switches)
    except (ValueError, OSError) as exc:
        print(f"History report failed: {exc}", file=sys.stderr)
        return 2
    print(f"History: {len(history['runs'])} runs; {history['candidate_count']} candidates for human review.")
    print(f"Report: {args.output / 'history.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
