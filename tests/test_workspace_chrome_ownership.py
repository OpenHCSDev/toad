"""Global navigation construction belongs to one application component."""

import ast
from pathlib import Path


def test_global_navigation_is_constructed_only_by_workspace_owner():
    root = Path(__file__).resolve().parents[1] / "src" / "toad"
    violations = []
    for path in root.rglob("*.py"):
        if path.name == "workspace_chrome.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in {"SessionsTabs", "TabHistoryControls", "ChannelsSidebar"}):
                violations.append((str(path.relative_to(root)), node.lineno, node.func.id))
    assert not violations, violations


def test_view_mount_and_agent_readiness_do_not_activate_a_shell():
    source = Path(__file__).resolve().parents[1] / "src" / "toad" / "widgets" / "conversation.py"
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {"initialize_view", "watch_agent_ready"}:
            assert not any(isinstance(item, ast.Attribute) and item.attr == "shell"
                           for item in ast.walk(node)), node.name
