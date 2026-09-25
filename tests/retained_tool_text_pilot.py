"""Streaming plain/ANSI tool output keeps its widget and exact copy semantics."""

import asyncio
import os
from pathlib import Path
import tempfile

from rich.text import Text
from runtime_fixture import ToadApp
from textual.content import Content
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection
from toad.widgets.tool_call import MarkdownContent, TextContent, ToolCall
from toad.widgets.worker_static import WorkerStatic


def payload(text, *, kind="execute", raw_input=None):
    return {"toolCallId": "stream", "title": "Synthetic output", "kind": kind,
            "status": "in_progress", "rawInput": raw_input or {},
            "content": [{"type": "content", "content": {"type": "text", "text": text}}]}


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-retained-tool-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            tool = ToolCall(payload("first"))
            await app.screen.conversation.post(tool)
            tool.set_expanded(True)
            await pilot.pause()
            original = tool.query_one(TextContent)
            values = ["[red]literal markup[/]\n界 é 🙂", "\x1b[31mred text\x1b[0m", "",
                      "\n".join(f"line {index}" for index in range(40)), "short"]
            for text in values:
                await tool.update_tool_call(payload(text))
                await pilot.pause()
                current = tool.query_one(TextContent)
                assert current is original
                expected = Content.from_rich_text(Text.from_ansi(text)) if "\x1b" in text else Content(text)
                assert current.render().plain == expected.plain
                assert current.render().spans == expected.spans
                assert current.get_selection(SELECT_ALL)[0] == expected.plain
                if text.startswith("line 0"):
                    assert current.size.height == 40
                elif text == "short":
                    assert current.size.height == 1

            long_text = "\n".join(f"line {index}" for index in range(40))
            await tool.update_tool_call(payload(long_text))
            app.screen.selections = {original: Selection(Offset(0, 30), Offset(4, 30))}
            await tool.update_tool_call(payload("tiny"))
            await pilot.pause()
            assert tool.query_one(TextContent) is not original
            assert not original.is_attached
            assert app.screen.get_selected_text() in (None, "")

            await tool.update_tool_call(payload("# Heading\n\nMarkdown body"))
            await pilot.pause()
            assert tool.query_one(MarkdownContent)
            await tool.update_tool_call(payload("plain again"))
            await pilot.pause()
            plain = tool.query_one(TextContent)
            assert not tool.query(MarkdownContent)

            code = "def example(value):\n    return value + 1\n"
            await tool.update_tool_call(payload(code, kind="read", raw_input={"path": "example.py"}))
            await pilot.pause()
            read = tool.query_one(WorkerStatic)
            await asyncio.wait_for(read.wait_ready(), 15)
            assert read._prepared is not None and any(line.text for line in read._prepared.lines)
            assert read.get_selection(SELECT_ALL)[0] == SELECT_ALL.extract(code)
            await tool.update_tool_call(payload("literal [red]markup[/]", kind="read",
                                                raw_input={"path": "unrecognized.unknown"}))
            unknown = tool.query_one(WorkerStatic)
            await asyncio.wait_for(unknown.wait_ready(), 10)
            assert unknown.get_selection(SELECT_ALL)[0] == "literal [red]markup[/]"
            await tool.update_tool_call(payload("plain after read"))
            await pilot.pause()
            assert not tool.query(WorkerStatic) and tool.query_one(TextContent) is not plain
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tool text: retained plain/ANSI widgets, literal markup, geometry, copy and selected/type-change fallbacks")


if __name__ == "__main__":
    asyncio.run(main())
