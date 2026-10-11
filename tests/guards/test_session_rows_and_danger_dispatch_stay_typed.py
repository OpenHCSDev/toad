"""Saved sessions are typed rows and the shell-danger analysis dispatches by declaration; the old callers stay deleted."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/toad"
TERMINAL_VARIABLES = {"FORCE_COLOR", "TTY_COMPATIBLE", "TERM", "COLORTERM", "TOAD", "CLICOLOR"}


def test_no_source_file_sets_terminal_variables_or_indexes_a_session_row():
    for path in SOURCE.rglob("*.py"):
        if path.name == "terminal_environment.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                        assert target.slice.value not in TERMINAL_VARIABLES, str(path)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "session"):
                raise AssertionError(f"Untyped session row caller: {path}:{node.lineno}")
    store = (SOURCE / "db.py").read_text()
    assert "cast(Session" not in store
    assert "promot_count" not in store
    assert "CREATE TABLE IF NOT EXISTS sessions" not in store


def test_danger_analysis_has_no_old_dispatch():
    source = (SOURCE / "danger.py").read_text()
    for old in ("hasattr", ".kind", "IntEnum", "max("):
        assert old not in source
    assert not (SOURCE / "widgets/danger_warning.py").exists()
    assert "_danger_level" not in (SOURCE / "widgets/prompt.py").read_text()
