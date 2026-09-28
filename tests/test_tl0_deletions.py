"""Retired local-session presentation and dead product modules stay deleted."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/toad"


def test_retired_local_sidebar_and_modules():
    removed_modules = (
        "code_analyze.py", "gist.py", "option_content.py", "os.py",
        "widgets/version.py", "widgets/welcome.py", "widgets/danger_warning.py",
    )
    assert not [name for name in removed_modules if (SOURCE / name).exists()]
    removed_symbols = {"SessionPresentation", "SessionRow", "SessionSidebar"}
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.ClassDef, ast.Name, ast.Attribute)):
                name = node.name if isinstance(node, ast.ClassDef) else node.id if isinstance(node, ast.Name) else node.attr
                assert name not in removed_symbols, (path, node.lineno, name)
    row_tree = ast.parse((SOURCE / "widgets/session_sidebar.py").read_text())
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "update_thread"
                   for node in ast.walk(row_tree))
    # This is the real worker entry point, not an unimported dead module.
    assert (SOURCE / "render_server.py").is_file()
    assert '"-m", "toad.render_server"' in (SOURCE / "render_zmq.py").read_text()


def test_current_model_configuration_only():
    tree = ast.parse((SOURCE / "acp/agent.py").read_text())
    publish = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "_publish_models")
    assert not any(isinstance(node, ast.Constant) and node.value in
                   {"models", "currentModelId", "availableModels"}
                   for node in ast.walk(publish))
