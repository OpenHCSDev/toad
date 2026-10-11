"""Tab history and clipboard mechanisms that were deleted stay deleted."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src/toad"
DELETED = {
    "_open_tab_order",
    "_tab_history",
    "_tab_history_index",
    "_supports_pyperclip",
    "_record_tab_visit",
    "_prune_tab_history",
    "_tab_history_target",
    "navigate_tab_history",
    "can_navigate_tab_history",
    "tab_history_changed",
}


def test_deleted_tab_history_names_and_pyperclip_imports_are_absent():
    for path in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in DELETED, (path, node.lineno, node.attr)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in DELETED, (path, node.lineno, node.name)
            if isinstance(node, ast.Import) and path.name != "clipboard.py":
                assert all(alias.name != "pyperclip" for alias in node.names), path
            if isinstance(node, ast.ImportFrom) and path.name != "clipboard.py":
                assert node.module != "pyperclip", path
    assert not (ROOT.parents[1] / "tests/clipboard_selection_pilot.py").exists()
