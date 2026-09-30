"""T3 guards against restoring maintained command rosters and dispatch."""
import ast
from pathlib import Path

def test_command_owners_have_no_parallel_dispatch():
    ROOT = Path(__file__).resolve().parents[2] / "src/toad"
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "SlashCommand":
                    raise AssertionError(f"Maintained slash roster: {path}:{node.lineno}")
                if node.func.id == "hasattr" and node.args and ast.unparse(node.args[0]) in {"self.agent", "agent"}:
                    raise AssertionError(f"Agent capability probe: {path}:{node.lineno}")
            if isinstance(node, ast.Compare):
                operands = (node.left, *node.comparators)
                # Shell command validation is outside the slash-command domain.
                if path.name == "conversation.py" and any(isinstance(x, ast.Name) and x.id in {"command", "name"} for x in operands):
                    assert not any(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in operands), (path, node.lineno)
                if path.name in {"mcp_inventory.py", "action_modal.py"}:
                    assert not any(isinstance(x, ast.Attribute) and x.attr == "id" for x in operands), (path, node.lineno)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in {"comms_start", "comms_stop", "comms_archive", "comms_ack", "comms_fork", "comms_delete"}:
                    assert path.name == "thread_actions.py", (path, node.lineno)

    for name in ("comms_sidebar.py", "comms_menu.py"):
        path = ROOT / "widgets" / name
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in ("copy", "pin", "any_mode", "close_view"):
                raise AssertionError(f"Duplicated UI action roster: {path}:{node.lineno}")

    targets = ROOT / "target_commands.py"
    for node in ast.walk(ast.parse(targets.read_text())):
        assert not isinstance(node, ast.Attribute) or node.attr != "is_thread", node.lineno
        assert not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or node.target.id != "is_thread", node.lineno


def test_catalog_action_consumers_do_not_classify_configured_names():
    """The original C0 case and its completion/result consumers stay deleted."""
    root = Path(__file__).resolve().parents[2] / "src/toad"
    retired = {"__launch__", "install", "install-acp", "install_acp",
               "install_adapter", "login", "launch"}
    for relative in ("screens/agent_modal.py", "screens/action_modal.py", "screens/store.py"):
        for node in ast.walk(ast.parse((root / relative).read_text())):
            if isinstance(node, (ast.Compare, ast.Match)):
                assert not any(isinstance(part, ast.Constant) and part.value in retired
                               for part in ast.walk(node)), (relative, node.lineno)
            if relative == "screens/agent_modal.py":
                assert not (isinstance(node, ast.Attribute) and node.attr == "action"), node.lineno
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    assert node.name not in {"watch_action", "on_button_pressed"}, node.lineno
