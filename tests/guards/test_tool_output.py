"""Tool output consumers cannot regain raw branches or duplicated state."""

import ast
import asyncio
from pathlib import Path

from textual.content import Content
from toad.tool_output import SpecificTextToolOutputPart, ToolOutputPart
from toad.widgets.tool_content import TextContent

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
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_worker":
                # Coroutines are created by Textual after worker entry. A
                # cancelled queued worker must own only an async callable.
                assert not isinstance(node.args[0], ast.Call) or (
                    isinstance(node.args[0].func, ast.Name) and node.args[0].func.id == "partial"
                ), (relative, node.lineno)


def test_new_case_adopts_the_installed_consumer_without_catalog_edits(tmp_path, monkeypatch):
    from importlib.resources import files
    from runtime_fixture import ToadApp
    from toad.widgets.tool_call import ToolCall

    class InspectionToolOutputPart(SpecificTextToolOutputPart):
        @classmethod
        def accepts(cls, text, read_path):
            return read_path is None and text.startswith("DECLARED_NEW_OUTPUT")

        def compose(self, view):
            return (TextContent(Content("case owns: " + self.text)),)

    for name, value in {"AGENT_COMMS_ROOT": tmp_path / "wire", "XDG_CONFIG_HOME": tmp_path / "config",
                        "XDG_STATE_HOME": tmp_path / "state", "XDG_DATA_HOME": tmp_path / "data"}.items():
        monkeypatch.setenv(name, str(value))

    async def run():
        app = ToadApp(project_dir=str(tmp_path))
        app.CSS_PATH = files("toad").joinpath("toad.tcss")
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            tool = ToolCall({"toolCallId": "new-case", "title": "New case", "status": "completed",
                "content": [{"type": "content", "content": {"type": "text", "text": "DECLARED_NEW_OUTPUT"}}]})
            tool.set_expanded(True)
            await app.screen.conversation.post(tool)
            await pilot.pause()
            assert InspectionToolOutputPart in ToolOutputPart.members_with(SpecificTextToolOutputPart)
            assert type(tool.output.parts[0]) is InspectionToolOutputPart
            assert tool.query_one(TextContent).render().plain == "case owns: DECLARED_NEW_OUTPUT"
            assert "case owns: DECLARED_NEW_OUTPUT" in "\n".join(
                strip.text for strip in app.screen._compositor.render_strips())
            tool.collapse_block()
            await pilot.pause()
            assert not tool.query(TextContent)
            tool.expand_block()
            await pilot.pause()
            assert tool.query_one(TextContent).render().plain == "case owns: DECLARED_NEW_OUTPUT"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()

    asyncio.run(run())
