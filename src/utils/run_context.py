"""Capture non-secret provenance before a run so historical comparisons have a scope."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Any


def source_hashes(root: Path) -> dict[str, str]:
    files = [p for directory in ("src", "config", "tests", "scripts", "fixtures")
             for p in sorted((root / directory).rglob("*"))
             if p.is_file() and p.suffix in {".py", ".json", ".jsonl"}]
    files.extend(root / name for name in (
        "conftest.py", "pytest-offline.ini", "pytest.ini", "pyproject.toml",
        "requirements.txt", "requirements-dev.txt",
    ) if (root / name).is_file())
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


def capture_context(
    root: Path, environment: str, selection: list[str], configuration: dict[str, str],
) -> dict[str, Any]:
    context = {
        "source_sha256": source_hashes(root),
        "packages": dict(sorted((d.metadata["Name"], d.version)
                                for d in importlib.metadata.distributions())),
        "python": sys.version,
        "platform": platform.platform(),
        "environment": environment,
        "test_selection": selection,
        "configuration": configuration,
    }
    digest = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return {**context, "context_digest": digest}
