"""Tool output consumers cannot regain raw branches or duplicated state."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_root_content_mechanisms_are_deleted():
    tree = ast.parse((ROOT / "src/toad/widgets/tool_call.py").read_text())
    deleted = {"_compose_content", "_simple_text_payload", "_schedule_patch_warmup",
               "_warm_patch_data", "_cancel_patch_warmup", "_sync_content",
               "_hydrate_visible_content", "_warm_theme_changed"}
    fields = {"_rendered_content", "_rendered_simple_text", "_warm_patches",
              "_warm_patch_sources", "_warm_patch_theme", "_warm_patch_generation",
              "_warm_patch_worker", "_content_lock", "_awaiting_visible_content",
              "_hydration_scheduled"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in deleted
        if isinstance(node, ast.Attribute):
            assert node.attr not in fields
        if isinstance(node, ast.Constant):
            assert node.value not in ("mimeType", "text/x-diff", "oldText", "newText", "content")
    assert not (ROOT / "tests/hidden_diff_warmup_pilot.py").exists()
    permission = ast.parse((ROOT / "src/toad/widgets/acp_content.py").read_text())
    assert not any(isinstance(node, ast.Match) for node in ast.walk(permission))
    assert not any(isinstance(node, ast.Name) and node.id in {"make_diff", "Markdown", "ToolCall"}
                   for node in ast.walk(permission))
    assert not any(isinstance(node, ast.Constant) and node.value in {
        "type", "text", "diff", "oldText", "newText", "path", "content"
    } for node in ast.walk(permission))
    for relative in ("src/toad/tool_output.py", "src/toad/widgets/tool_content.py"):
        source = (ROOT / relative).read_text()
        assert "__registry__ =" not in source and "Enum" not in source
        assert "Fallback" not in source
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.BoolOp):
                assert len(node.values) < 4, (relative, node.lineno)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"_awaiting_visible", "_hydration_scheduled", "_presentable",
                                         "_prepared_patch", "_requested_theme"}, (relative, node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_worker":
                # Coroutines are created by Textual after worker entry. A
                # cancelled queued worker must own only an async callable.
                assert not isinstance(node.args[0], ast.Call) or (
                    isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "partial"
                ), (relative, node.lineno)
