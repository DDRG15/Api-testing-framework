from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from export_source import export_source  # noqa: E402


def repository(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("*.local\n")
    (root / "example.py").write_text("answer = 42\n")
    return root


def test_export_has_current_source_but_no_ignored_material_or_git_metadata(tmp_path):
    root = repository(tmp_path)
    (root / "settings.local").write_text("synthetic private material")
    output = tmp_path / "export"
    manifest = export_source(root, output, [])
    with zipfile.ZipFile(output / "source.zip") as archive:
        assert set(archive.namelist()) == {".gitignore", "example.py"}
        assert archive.read("example.py") == b"answer = 42\n"
    assert str(tmp_path) not in str(manifest)
    with pytest.raises(ValueError, match="new_output"):
        export_source(root, output, [])


def test_sensitive_working_source_is_rejected_before_creating_export(tmp_path):
    root = repository(tmp_path)
    (root / "example.py").write_text('identity = "synthetic-blocked-identity"\n')
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="publication_findings"):
        export_source(root, output, ["synthetic-blocked-identity"])
    assert not output.exists()


def test_export_preserves_executable_launcher_without_owner_metadata(tmp_path):
    root = repository(tmp_path)
    launcher = root / "api-lab"
    launcher.write_text("#!/usr/bin/env bash\nexit 0\n")
    launcher.chmod(0o755)
    output = tmp_path / "export"
    manifest = export_source(root, output, [])
    with zipfile.ZipFile(output / "source.zip") as archive:
        entry = archive.getinfo("api-lab")
        assert entry.create_system == 3
        assert (entry.external_attr >> 16) & 0o777 == 0o755
        assert not entry.extra
    assert manifest["file_modes"]["api-lab"] == 0o755
    assert manifest["file_modes"]["example.py"] == 0o644
