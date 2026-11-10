from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_publication import PublicationError, audit_repository, inspect_text

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repository(tmp_path):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


@pytest.mark.parametrize("value,category", [
    ("ghp_" + "a" * 36, "provider_token"),
    ("github_pat_" + "a" * 40, "provider_token"),
    ("AKIA" + "A" * 16, "provider_token"),
    ("sk-proj-" + "a" * 32, "provider_token"),
    ("sk_live_" + "a" * 32, "provider_token"),
    ("-----BEGIN " + "PRIVATE KEY-----", "private_key"),
    ("-----BEGIN " + "OPENSSH PRIVATE KEY-----", "private_key"),
    ("eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12, "jwt"),
    ("https://" + "account:credential@host.invalid/api", "credential_url"),
    ("/" + "home/fixture-owner/repository", "personal_home_path"),
    ("C:" + "\\Users\\fixture-owner\\repository", "personal_home_path"),
    ("person" + "@" + "mail-provider.com", "non_example_email"),
])
def test_sensitive_patterns_report_only_categories_and_locations(value, category):
    findings = inspect_text("source.txt", "safe\n" + value + "\n")
    assert {"path": "source.txt", "line": 2, "category": category} in findings
    assert value not in json.dumps(findings)


def test_examples_synthetic_data_and_operational_placeholders_are_allowed():
    text = "\n".join([
        "API_USERNAME=admin", "API_PASSWORD=password123", "API_TOKEN=<YOUR_API_TOKEN>",
        "contact=person@example.com", "contact=person@subdomain.example.org",
        "contact=person@project.test", "contact=person@project.invalid",
        "path=/home/user/project", "path=/Users/username/project", "synthetic-test-signing-secret",
    ])
    assert inspect_text("example.txt", text) == []


def test_optional_identity_terms_are_literal_case_insensitive_and_not_echoed():
    identity = "fixture" + "owner+[1]"
    findings = inspect_text("configuration.txt", "line one\n" + identity.upper(), [identity])
    assert findings == [{"path": "configuration.txt", "line": 2, "category": "blocked_identifier"}]
    assert identity.casefold() not in json.dumps(findings).casefold()
    assert inspect_text("configuration.txt", "fixtureowner11", [identity]) == []


def test_ignored_private_files_are_not_read_and_force_tracked_ignores_are_flagged(repository):
    (repository / ".gitignore").write_text("private/\n*.local\n")
    (repository / "public.py").write_text("print('example')\n")
    (repository / "private").mkdir()
    (repository / "private/notes.txt").write_text("ghp_" + "a" * 36)
    (repository / "settings.local").write_text("ghp_" + "b" * 36)
    subprocess.run(["git", "-C", str(repository), "add", ".gitignore", "public.py"], check=True)
    assert audit_repository(repository)["findings"] == []
    subprocess.run(["git", "-C", str(repository), "add", "--force", "settings.local"], check=True)
    assert audit_repository(repository)["findings"] == [
        {"path": "settings.local", "line": 0, "category": "ignored_tracked"},
    ]


def test_untracked_public_candidates_are_scanned_but_symlink_targets_are_not(repository):
    (repository / "candidate.txt").write_text("person" + "@" + "mail-provider.com")
    (repository / "link.txt").symlink_to(repository / "outside-does-not-exist")
    result = audit_repository(repository)
    assert {item["category"] for item in result["findings"]} == {"non_example_email", "symlink_candidate"}


def test_deleted_indexed_files_cannot_silently_pass(repository):
    candidate = repository / "candidate.txt"
    candidate.write_text("safe")
    subprocess.run(["git", "-C", str(repository), "add", "candidate.txt"], check=True)
    candidate.unlink()
    assert audit_repository(repository)["findings"] == [
        {"path": "candidate.txt", "line": 0, "category": "missing_indexed_file"},
    ]
    subprocess.run(["git", "-C", str(repository), "rm", "--cached", "candidate.txt"], check=True, capture_output=True)
    assert audit_repository(repository)["findings"] == []


def test_clean_working_copy_cannot_hide_a_staged_secret(repository):
    candidate = repository / "candidate.txt"
    candidate.write_text("ghp_" + "a" * 36)
    subprocess.run(["git", "-C", str(repository), "add", "candidate.txt"], check=True)
    candidate.write_text("safe working copy")
    assert audit_repository(repository)["findings"] == [
        {"path": "candidate.txt", "line": 1, "category": "provider_token"},
    ]
    # Scanning both identical versions must not double-count one finding.
    candidate.write_text("ghp_" + "a" * 36)
    assert len(audit_repository(repository)["findings"]) == 1


def test_binary_and_non_utf8_files_are_explicitly_counted(repository):
    (repository / "image.bin").write_bytes(b"\x00\xff")
    (repository / "encoded.bin").write_bytes(b"\xff\xfe")
    report = audit_repository(repository)
    assert report["binary_skipped"] == 2
    assert report["scanned_files"] == 0
    assert report["findings"] == []


def test_missing_repository_reports_a_category_without_root_path(tmp_path):
    with pytest.raises(PublicationError, match="repository_unavailable"):
        audit_repository(tmp_path)
    command = subprocess.run(
        [sys.executable, "scripts/check_publication.py", "--root", str(tmp_path), "--json"],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert command.returncode == 2
    assert json.loads(command.stdout) == {"error": "repository_unavailable"}
    assert str(tmp_path) not in command.stdout + command.stderr


def test_cli_exit_codes_and_json_do_not_expose_blocked_values(repository):
    identity = "fixture" + "owner-private"
    candidate = repository / "public.txt"
    candidate.write_text(identity)
    env = {**os.environ, "PUBLICATION_BLOCK_TERMS": identity}
    command = [sys.executable, "scripts/check_publication.py", "--root", str(repository), "--json"]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert json.loads(result.stdout)["findings"] == [
        {"path": "public.txt", "line": 1, "category": "blocked_identifier"},
    ]
    assert identity not in result.stdout + result.stderr
    candidate.write_text("safe")
    assert subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=10).returncode == 0
