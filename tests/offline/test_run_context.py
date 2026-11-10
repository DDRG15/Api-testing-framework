from pathlib import Path

from src.utils.run_context import capture_context, source_hashes


def test_context_is_stable_but_separates_code_environment_and_selection(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    code = source / "client.py"
    code.write_text("version = 1\n")
    baseline = capture_context(tmp_path, "offline", [], {"timeout": "1"})
    assert baseline == capture_context(tmp_path, "offline", [], {"timeout": "1"})
    for environment, selection, config in [
        ("staging", [], {"timeout": "1"}),
        ("offline", ["-n", "2"], {"timeout": "1"}),
        ("offline", [], {"timeout": "2"}),
    ]:
        assert baseline["context_digest"] != capture_context(tmp_path, environment, selection, config)["context_digest"]
    code.write_text("version = 2\n")
    assert baseline["context_digest"] != capture_context(tmp_path, "offline", [], {"timeout": "1"})["context_digest"]


def test_source_snapshot_includes_contracts_and_configuration_not_outputs(tmp_path: Path):
    contracts = tmp_path / "fixtures"
    contracts.mkdir()
    (contracts / "case.jsonl").write_text('{"case":"synthetic"}\n')
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/response.json").write_text("{}")
    assert set(source_hashes(tmp_path)) == {"fixtures/case.jsonl", "pytest.ini"}
