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
    removed_symbols = {"SessionPresentation", "SessionRow", "SessionSidebar", "McpSettings",
                       "in_out_only", "_run_test_hook", "_compatibility",
                       "POSITIVE_DECISIONS_CAPABILITY", "positive_decisions", "send_prompt_to_agent", "send_queued_now",
                       "_sending_queue_input_id", "TokenUsage", "_token_usage", "_send_prompt", "_acp_session_prompt", "acp_session_prompt", "acp_session_cancel", "_owner_request", "rpc_session_update", "_rpc_session_update", "_apply_session_update", "_reject_session_update", "rpc_request_permission", "rpc_read_text_file",
                       "rpc_write_text_file", "rpc_terminal_create", "rpc_terminal_output",
                       "rpc_terminal_kill", "rpc_terminal_release", "rpc_terminal_wait_for_exit"}
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Name, ast.Attribute)):
                name = node.name if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else node.id if isinstance(node, ast.Name) else node.attr
                assert name not in removed_symbols, (path, node.lineno, name)
    row_tree = ast.parse((SOURCE / "widgets/session_sidebar.py").read_text())
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "update_thread"
                   for node in ast.walk(row_tree))
    # This is the real worker entry point, not an unimported dead module.
    assert (SOURCE / "render_server.py").is_file()
    assert '"-m", "toad.render_server"' in (SOURCE / "render_zmq.py").read_text()



def test_no_product_test_environment_switch():
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                environment = ast.unparse(node.func.value)
                if environment == "os.environ" or (environment == "os" and node.func.attr == "getenv"):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        assert "TEST" not in str(node.args[0].value), (path, node.lineno)
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant):
                    assert "TEST" not in str(node.slice.value), (path, node.lineno)
