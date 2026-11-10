"""Summarize phase JSONL; corrupt, duplicate or empty evidence fails explicitly."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.test_results import load_events, markdown_summary, summarize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(load_events(args.inputs))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.output / "summary.md").write_text(markdown_summary(summary), encoding="utf-8")
    print(f"Evidence: {summary['total']} tests; {summary['passed_after_rerun']} recovered reruns")
    return int(not summary["total"] or summary["failed"] > 0 or summary["incomplete"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
