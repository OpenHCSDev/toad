"""One workspace roster and declared cases replace App's repeated authority."""
import ast
from pathlib import Path


def test_complete_root_admission_caller_deletion():
    root = Path(__file__).resolve().parents[2] / "src/toad"
    retired = {"_comms_modes", "_comms_mode_index", "_file_preview_modes", "_file_preview_index",
               "_file_preview_return", "_thread_openings", "open_thread_session",
               "_finish_open_thread_session", "open_comms_session", "_open_comms_history",
               "new_session_screen", "close_session_mode", "return_from_preview",
               "_main_session_screen", "coordination_wire", "_coordination_wire", "_coordination_route",
               "pending_thread_actions", "invoke_thread_action", "_run_thread_action",
               "open_wire_export_dialog", "open_thread_import_dialog", "_export_wire", "_import_thread"}
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired, (path, node.lineno, node.attr)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in retired, (path, node.lineno, node.name)
    for relative in ("session_admission.py", "session_navigation.py", "thread_navigation.py"):
        for node in ast.walk(ast.parse((root / relative).read_text())):
            if isinstance(node, ast.ClassDef):
                assert not node.name.endswith("Mixin"), (relative, node.name)
            if relative == "session_navigation.py" and isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in {"isinstance", "getattr", "hasattr"}, (relative, node.lineno)
