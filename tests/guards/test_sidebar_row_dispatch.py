"""Row-kind dispatch in the sidebar stays deleted: a destination is a target class."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src/toad"
FILES = ("navigation_target.py", "widgets/comms_sidebar.py", "widgets/thread_comms.py")


def test_retired_row_dispatch_is_absent():
    for relative in FILES:
        for node in ast.walk(ast.parse((SOURCE / relative).read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "kind" and isinstance(node.value, ast.Name):
                assert node.value.id not in {"row", "choice"}, relative
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "NavigationTarget":
                    assert node.func.attr != "decode", relative
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert node.target.id != "kind", relative
