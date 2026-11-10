"""Inspect Git publication candidates without printing matched sensitive values.

Only index entries and non-ignored untracked files are considered. Locally
ignored tracked paths are flagged without reading their content. This is a
bounded text-pattern check, not a complete secret scanner or history rewrite.
Set PUBLICATION_BLOCK_TERMS to comma-separated literal identifiers for an
additional local identity check; never commit a personal blocklist.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 10 * 1024 * 1024
_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "provider_token": re.compile(
        r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{25,}"
        r"|github_pat_[A-Za-z0-9_]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16}"
        r"|sk-[A-Za-z0-9_-]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}"
        r"|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{35})"
    ),
    "jwt": re.compile(r"(?<![A-Za-z0-9_])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "credential_url": re.compile(r"\b(?:https?|redis|postgres(?:ql)?)://[^\s/:@]+:[^\s/@]+@"),
}
_HOME = re.compile(
    r"(?:/(?:home|Users)/|[A-Za-z]:\\{1,2}Users\\{1,2})([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(?<![\w.-])[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PLACEHOLDER_USERS = {"user", "username", "your-user", "your_username", "example"}
_EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net"}


class PublicationError(Exception):
    """An audit could not be completed; error messages contain categories only."""


def _example_domain(domain: str) -> bool:
    domain = domain.lower().rstrip(".")
    return (domain in _EXAMPLE_DOMAINS
            or any(domain.endswith("." + item) for item in _EXAMPLE_DOMAINS)
            or domain.endswith((".example", ".invalid", ".test")))


def inspect_text(path: str, content: str, block_terms: list[str] | None = None) -> list[dict[str, Any]]:
    """Return locations/categories, never regex matches or source excerpts."""
    terms = [term.casefold() for term in (block_terms or []) if term.strip()]
    findings = []
    for number, line in enumerate(content.splitlines(), 1):
        categories = {name for name, pattern in _PATTERNS.items() if pattern.search(line)}
        if any(match.group(1).casefold() not in _PLACEHOLDER_USERS for match in _HOME.finditer(line)):
            categories.add("personal_home_path")
        if any(not _example_domain(match.group(1)) for match in _EMAIL.finditer(line)):
            categories.add("non_example_email")
        lowered = line.casefold()
        if any(term in lowered for term in terms):
            categories.add("blocked_identifier")
        findings.extend({"path": path, "line": number, "category": category}
                        for category in sorted(categories))
    return findings


def _git(root: Path, arguments: list[str], data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments], input=data, capture_output=True, check=False,
        )
    except OSError as exc:
        raise PublicationError("git_unavailable") from exc
    if completed.returncode not in (0, 1):
        raise PublicationError("repository_unavailable")
    return completed


def audit_repository(root: Path, block_terms: list[str] | None = None) -> dict[str, Any]:
    """Inspect publication candidates from a repository root, without following links."""
    probe = _git(root, ["rev-parse", "--show-toplevel"])
    if probe.returncode or Path(os.fsdecode(probe.stdout).strip()).resolve() != root.resolve():
        raise PublicationError("select_repository_root")
    index_entries = _git(root, ["ls-files", "--stage", "-z"]).stdout.split(b"\0")
    index_blobs = {}
    for entry in index_entries:
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, oid, stage = header.split()
        if stage != b"0":
            raise PublicationError("unmerged_index")
        index_blobs[name] = (mode, oid)
    indexed = list(index_blobs)
    untracked = _git(root, ["ls-files", "--others", "--exclude-standard", "-z"]).stdout.split(b"\0")
    ignored = set()
    if indexed:
        ignored = set(_git(root, ["check-ignore", "--no-index", "--stdin", "-z"],
                           b"\0".join(indexed) + b"\0").stdout.split(b"\0"))
    findings: list[dict[str, Any]] = []
    scanned = 0
    binary = 0
    for raw_name in sorted(set(indexed + untracked) - {b""}):
        name = os.fsdecode(raw_name)
        path = root / name
        if raw_name in ignored:
            findings.append({"path": name, "line": 0, "category": "ignored_tracked"})
            continue
        if path.is_symlink():
            findings.append({"path": name, "line": 0, "category": "symlink_candidate"})
            continue
        if not path.exists():
            # An unstaged deletion remains in the index and would still publish.
            findings.append({"path": name, "line": 0, "category": "missing_indexed_file"})
            continue
        if not path.is_file():
            findings.append({"path": name, "line": 0, "category": "unsupported_candidate"})
            continue
        try:
            if path.stat().st_size > MAX_TEXT_BYTES:
                findings.append({"path": name, "line": 0, "category": "oversized_candidate"})
                continue
            payloads = [path.read_bytes()]
        except OSError as exc:
            raise PublicationError("candidate_unreadable") from exc
        if raw_name in index_blobs:
            mode, oid = index_blobs[raw_name]
            if mode not in (b"100644", b"100755"):
                findings.append({"path": name, "line": 0, "category": "unsupported_index_entry"})
                continue
            blob_id = oid.decode("ascii")
            blob_size = int(_git(root, ["cat-file", "-s", blob_id]).stdout)
            if blob_size > MAX_TEXT_BYTES:
                findings.append({"path": name, "line": 0, "category": "oversized_candidate"})
                continue
            # A clean working copy must not hide a staged secret in the index.
            payloads.append(_git(root, ["cat-file", "blob", blob_id]).stdout)
        text_seen = False
        binary_seen = False
        for data in payloads:
            try:
                content = data.decode("utf-8") if b"\0" not in data else None
            except UnicodeDecodeError:
                content = None
            if content is None:
                binary_seen = True
            else:
                text_seen = True
                findings.extend(inspect_text(name, content, block_terms))
        scanned += int(text_seen)
        binary += int(binary_seen)
    unique = {(item["path"], item["line"], item["category"]) for item in findings}
    return {"scanned_files": scanned, "binary_skipped": binary,
            "findings": [{"path": path, "line": line, "category": category}
                         for path, line, category in sorted(unique)]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Git repository root")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report on stdout")
    args = parser.parse_args()
    terms = [term.strip() for term in os.environ.get("PUBLICATION_BLOCK_TERMS", "").split(",") if term.strip()]
    try:
        report = audit_repository(args.root.resolve(), terms)
    except PublicationError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Publication check error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for finding in report["findings"]:
            print(f"{finding['path']}:{finding['line']}: {finding['category']}")
        print(f"Scanned {report['scanned_files']} text files; skipped {report['binary_skipped']} binary files; "
              f"findings: {len(report['findings'])}. Matched values are not printed.")
    return int(bool(report["findings"]))


if __name__ == "__main__":
    raise SystemExit(main())
