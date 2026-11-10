"""Check by default; use --update only to deliberately review a new baseline."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.utils.contracts import check_snapshots, write_snapshots  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--directory", type=Path, default=ROOT / "fixtures/contracts")
    args = parser.parse_args()
    if args.update:
        write_snapshots(args.directory)
    changed = check_snapshots(args.directory)
    if changed:
        print("Contract drift (review before updating): " + ", ".join(changed))
        return 1
    print("Model contract snapshots match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
