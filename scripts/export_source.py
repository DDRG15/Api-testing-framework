"""Export reviewed working source without Git metadata, ignored files or host paths."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from check_publication import MAX_TEXT_BYTES, ROOT, PublicationError, audit_repository, inspect_text


def export_source(root: Path, output: Path, block_terms: list[str]) -> dict:
    """Check index and working copies, then recheck exact bytes written to the ZIP."""
    report = audit_repository(root, block_terms)
    if report["findings"]:
        raise ValueError("publication_findings_require_review")
    root, output = root.resolve(), output.expanduser().resolve()
    if output.exists() or output == root or root in output.parents:
        raise ValueError("select_new_output_outside_repository")
    result = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others",
                             "--exclude-standard", "-z"], check=True, capture_output=True)
    payload = {}
    modes = {}
    for name in sorted(set(filter(None, result.stdout.split(b"\0")))):
        relative = os.fsdecode(name)
        path = root / relative
        if (path.is_symlink() or not path.resolve().is_relative_to(root)
                or not path.is_file() or path.stat().st_size > MAX_TEXT_BYTES):
            raise ValueError("source_changed_or_unsupported_file")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None and inspect_text(relative, text, block_terms):
            raise ValueError("source_changed_sensitive_content")
        payload[relative] = data
        modes[relative] = 0o755 if path.stat().st_mode & 0o111 else 0o644
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(output / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            # ZIP metadata carries neither filesystem ownership nor machine paths.
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | modes[name]) << 16
            archive.writestr(entry, data)
    manifest = {"created_utc": datetime.now(UTC).isoformat(), "scope": "working_source_without_git_metadata",
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()},
                "file_modes": modes,
                "archive_sha256": hashlib.sha256((output / "source.zip").read_bytes()).hexdigest(),
                "publication_check": report}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path.home() / "sandbox/enterprise-api-testing-framework/exports" / str(uuid.uuid4()))
    args = parser.parse_args()
    terms = [term.strip() for term in os.environ.get("PUBLICATION_BLOCK_TERMS", "").split(",") if term.strip()]
    try:
        manifest = export_source(ROOT, args.output, terms)
    except (OSError, ValueError, PublicationError, subprocess.CalledProcessError):
        print("Source export failed; run the publication check and select a new output directory.", file=sys.stderr)
        return 1
    print(f"Exported {len(manifest['files'])} source files. Review the archive before sharing.")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
