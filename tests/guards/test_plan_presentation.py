"""Permanent caller deletion for the plan presentation."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_plan_raw_consumers_and_switches_are_deleted():
    for path in (ROOT / "src/toad").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "Entry":
                assert not isinstance(node.value, ast.Name) or node.value.id != "Plan", (path, node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "on_acp_plan":
                assert not any(isinstance(child, ast.Constant) and child.value in
                               {"content", "priority", "status"} for child in ast.walk(node)), path
    for relative in ("src/toad/plan.py", "src/toad/widgets/plan.py"):
        source = (ROOT / relative).read_text()
        tree = ast.parse(source)
        assert "PRIORITIES" not in source and "render_status" not in source
        assert "__main__" not in source and "__registry__" not in source
        assert not any(isinstance(node, ast.Match) for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp):
                assert len(node.values) < 4, (relative, node.lineno)
            if isinstance(node, ast.Constant):
                assert node.value not in {"pending", "in_progress", "completed"}, (relative, node.lineno)
    prompt = ast.parse((ROOT / "src/toad/widgets/prompt.py").read_text())
    assert not any(isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                   and node.target.id == "plan" for node in ast.walk(prompt))
