"""Compare foreground Read highlighting and shared worker preparation on one scene."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from pygments.lexers import get_lexer_for_filename
from rich.syntax import Syntax
from textual.content import Content
from textual.selection import SELECT_ALL

from runtime_fixture import ToadApp
from toad.widgets.tool_call import TextContent, ToolCall
from toad.widgets.worker_static import WorkerStatic


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-tool-read-latency-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        source = "# café 界\n" + "def calculate(value: int) -> int:\n    return value + 1\n\n" * 1500
        native = ToolCall._compose_content

        def foreground_read(tool, content):
            # Keep the same historical Read branch as a fixture-only control.
            if tool.tool_call and tool.tool_call.get("kind") == "read":
                raw = tool.tool_call.get("rawInput") or {}
                filename = raw["path"]
                text = content[0]["content"]["text"]
                lexer = get_lexer_for_filename(filename)
                highlighted = Content.from_rich_text(Syntax(
                    text, lexer, theme="ansi_dark" if tool.app.current_theme.dark else "ansi_light",
                    background_color="default",
                ).highlight(text))
                yield TextContent(Content(text, list(highlighted.spans)))
            else:
                yield from native(tool, content)

        app = ToadApp(project_dir=str(root))
        results = []
        async with app.run_test(size=(110, 35)) as pilot:
            await pilot.pause()
            for index, kind in enumerate(("native", "worker", "worker", "native")):
                gaps = []

                async def pulse():
                    previous = time.perf_counter()
                    while True:
                        await asyncio.sleep(.005)
                        now = time.perf_counter()
                        gaps.append((now - previous) * 1000)
                        previous = now

                heartbeat = asyncio.create_task(pulse())
                await asyncio.sleep(0)
                task = ToolCall({"toolCallId": f"read-{index}", "kind": "read", "title": "Read example.py",
                                 "status": "completed", "rawInput": {"path": "example.py"},
                                 "content": [{"type": "content", "content": {"type": "text", "text": source}}]})
                before = time.thread_time_ns()
                started = time.perf_counter_ns()
                try:
                    with patch.object(ToolCall, "_compose_content", foreground_read if kind == "native" else native):
                        await app.screen.conversation.post(task)
                        task.set_expanded(True)
                        if kind == "worker":
                            async with asyncio.timeout(25):
                                while not task.query(WorkerStatic):
                                    await asyncio.sleep(.005)
                            await asyncio.wait_for(task.query_one(WorkerStatic).wait_ready(), 25)
                            widget = task.query_one(WorkerStatic)
                        else:
                            async with asyncio.timeout(25):
                                while not task.query(TextContent):
                                    await asyncio.sleep(.005)
                            widget = task.query_one(TextContent)
                        await pilot.pause()
                    ready_ms = (time.perf_counter_ns() - started) / 1e6
                    cpu_ms = (time.thread_time_ns() - before) / 1e6
                    actual = widget.get_selection(SELECT_ALL)[0]
                    expected = SELECT_ALL.extract(source)
                    assert actual == expected, (kind, len(actual), len(expected), repr(actual[:90]), repr(actual[-90:]))
                    results.append({"kind": kind, "ready_ms": round(ready_ms, 2),
                                    "ui_thread_cpu_ms": round(cpu_ms, 2),
                                    "max_event_loop_gap_ms": round(max(gaps, default=0), 2)})
                finally:
                    heartbeat.cancel()
                    await asyncio.gather(heartbeat, return_exceptions=True)
        await asyncio.get_running_loop().shutdown_default_executor()
        print(json.dumps({"boundary": "mounted Read tool ready in headless Toad; not terminal pixels",
                          "source_bytes": len(source.encode()), "samples": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
