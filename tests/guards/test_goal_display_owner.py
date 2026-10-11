"""The goal widgets hold no goal state of their own; the display model owns it."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src/toad"


@pytest.mark.parametrize("relative, retired", [
    ("widgets/goal_bar.py", {"goal", "unavailable"}),
    ("screens/goal_details.py", {"goal", "unavailable"}),
    ("widgets/conversation.py", {"goal", "goal_unavailable"}),
])
def test_widgets_have_one_goal_state(relative, retired):
    for node in ast.walk(ast.parse((SOURCE / relative).read_text())):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            assert node.attr not in retired, (relative, node.lineno)
        if isinstance(node, ast.ClassDef):
            for declaration in node.body:
                if isinstance(declaration, ast.AnnAssign) and isinstance(declaration.target, ast.Name):
                    assert declaration.target.id not in retired, (relative, declaration.lineno)
