"""The actual harness keeps failure evidence and never substitutes catalogue verdicts."""

import os
from pathlib import Path

pytest_plugins = ("pytester",)

TESTS = Path(__file__).resolve().parents[1]


def test_catalogue_notes_preserve_real_app_and_unit_outcomes(pytester, monkeypatch):
    (pytester.path / "conftest.py").symlink_to(TESTS / "conftest.py")
    (pytester.path / "test_outcome_probe.py").symlink_to(TESTS / "support/harness_probe.py")
    pytester.makeini("[pytest]\naddopts =\n")
    (pytester.path / "open_defects.toml").write_text('''
[recorded_investigation]
owner = "harness regression"
defect = "OLD_CATALOGUE_DEFECT_DOES_NOT_IDENTIFY_THIS_FAILURE"
intermittent = false
tests = ["test_outcome_probe.py::test_app_failure", "test_outcome_probe.py::test_unit_failure",
         "test_outcome_probe.py::test_app_pass", "test_outcome_probe.py::test_unit_pass"]
''')
    attempts = pytester.path / "attempts"
    attempts.mkdir()
    monkeypatch.setenv("TMPDIR", str(attempts))
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(TESTS), str(TESTS.parent / "src"),
                                                  os.environ.get("PYTHONPATH", ""))))
    result = pytester.runpytest_subprocess("-q", "--tb=short")
    result.assert_outcomes(passed=2, failed=2)
    output = result.stdout.str()
    assert "ACTUAL_APP_FAILURE_DIFFERS_FROM_CATALOGUE" in output
    assert "ACTUAL_UNIT_FAILURE_DIFFERS_FROM_CATALOGUE" in output
    assert "OLD_CATALOGUE_DEFECT_DOES_NOT_IDENTIFY_THIS_FAILURE" in output
    kept, = attempts.glob("toad-test-*")
    assert (kept / "original-evidence.txt").read_text() == "Retain the actual failed attempt"
    assert "ACTUAL_APP_FAILURE_DIFFERS_FROM_CATALOGUE" in (kept / "stdout.log").read_text()
    assert (kept / "stderr.log").is_file()
    assert (kept / "result.jsonl").is_file()
