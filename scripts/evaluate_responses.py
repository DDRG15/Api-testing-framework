"""Evaluate recorded JSONL responses with schema and approved numeric rules."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.response_evaluation import (  # noqa: E402
    EvaluationConfigError,
    evaluate_records,
    evaluation_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", type=Path)
    parser.add_argument("--input", dest="named_inputs", action="append", type=Path, default=[])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New artifact directory; reuse is rejected")
    args = parser.parse_args()
    inputs = [*args.inputs, *args.named_inputs]
    if not inputs:
        parser.error("at least one input file is required")
    if args.output.exists():
        print("Evaluation failed: output_directory_already_exists", file=sys.stderr)
        return 2
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        records = []
        for path in inputs:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    # Preserve line position and a failed record, never its text.
                    records.append(None)
        report = evaluate_records(records, config)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("Evaluation failed: unreadable_input_or_config", file=sys.stderr)
        return 2
    except EvaluationConfigError as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.output / "evaluation.md").write_text(evaluation_markdown(report), encoding="utf-8")
    except OSError:
        print("Evaluation failed: cannot_create_artifacts", file=sys.stderr)
        return 2
    print(f"Records: {report['total_records']}; failed: {report['failed_records']}; groups: {len(report['groups'])}")
    return int(report["failed_records"] > 0 or not report["total_records"])


if __name__ == "__main__":
    raise SystemExit(main())
