"""Build React assets with all dependencies and outputs in an external sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_console(sandbox: Path) -> Path:
    """Reuse only an unchanged successful build; never install into the repository."""
    sandbox = sandbox.expanduser().resolve()
    if not sandbox.is_relative_to((Path.home() / "sandbox").resolve()):
        raise ValueError("Console resources must be beneath ~/sandbox")
    if sandbox == ROOT or ROOT in sandbox.parents:
        raise ValueError("The console sandbox must be outside the repository")
    if not shutil.which("node") or not shutil.which("npm"):
        raise ValueError("Install Node.js 22.12+ and npm before building the console")
    version = subprocess.check_output(["node", "-p", "process.versions.node"], text=True).strip()
    major, minor = (int(part) for part in version.split(".")[:2])
    if major < 22 or (major == 22 and minor < 12):
        raise ValueError("Node.js 22.12+ is required")
    source = ROOT / "ui"
    files = sorted(path for path in source.rglob("*") if path.is_file()
                   and not {"node_modules", "dist", ".git"}.intersection(path.relative_to(source).parts))
    fingerprint = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise ValueError("Console source symlinks are not supported")
        fingerprint.update(str(path.relative_to(source)).encode())
        fingerprint.update(path.read_bytes())
    digest = fingerprint.hexdigest()
    workspace = sandbox / "console-builds" / digest
    manifest = workspace / "build.json"
    if manifest.is_file() and (workspace / "dist/index.html").is_file():
        state = json.loads(manifest.read_text())
        if state.get("source_sha256") == digest and state.get("node") == version:
            return workspace / "dist"
    workspace.mkdir(parents=True, exist_ok=True)
    for path in files:
        target = workspace / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (workspace / "tmp").mkdir(exist_ok=True)
    env = {**os.environ, "npm_config_cache": str(sandbox / "npm-cache"),
           "TMPDIR": str(workspace / "tmp"), "npm_config_update_notifier": "false"}
    for command in (["npm", "ci", "--ignore-scripts", "--no-fund"],
                    ["npm", "audit", "--audit-level=high"], ["npm", "run", "build"]):
        subprocess.run(command, cwd=workspace, env=env, check=True)
    manifest.write_text(json.dumps({"source_sha256": digest, "node": version}, indent=2) + "\n")
    return workspace / "dist"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path, default=Path.home() / "sandbox/enterprise-api-testing-framework")
    args = parser.parse_args()
    try:
        print(f"Console assets: {build_console(args.sandbox)}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f"Console build failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
