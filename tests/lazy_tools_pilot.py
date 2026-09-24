"""Long tool-heavy histories must not construct collapsed output trees."""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from toad.app import ToadApp
from toad.widgets.tool_call import ToolCall, ToolCallHeader, MarkdownContent
from toad.widgets.agent_response import AgentResponse
from toad.widgets.agent_thought import AgentThought
from toad.widgets.transcript_history import TranscriptHistory
from textual.widgets import Markdown


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-lazy-tools-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.settings.set("tools.expand", "never")
            text = "\n\n".join(f"## Section {i}\n\nOutput paragraph {i}" for i in range(40))
            tools = [
                ToolCall({
                    "toolCallId": f"tool-{i}",
                    "title": f"Read {i}",
                    "kind": "read",
                    "status": "completed",
                    "content": [{"type": "content", "content": {"type": "text", "text": text}}],
                })
                for i in range(40)
            ]
            ticks = []

            async def heartbeat():
                previous = time.perf_counter()
                while True:
                    await asyncio.sleep(.02)
                    now = time.perf_counter()
                    ticks.append(now - previous)
                    previous = now

            pulse = asyncio.create_task(heartbeat())
            start, cpu = time.perf_counter(), time.process_time()
            try:
                await app.screen.conversation.contents.mount(*tools)
                await pilot.pause()
                header = tools[-1].query_one(ToolCallHeader)
                for _ in range(5):
                    await tools[-1].update_tool_call(dict(tools[-1].tool_call))
                await pilot.pause()
                metrics = {
                    "seconds": time.perf_counter() - start,
                    "cpu_seconds": time.process_time() - cpu,
                    "tool_widgets": sum(len(list(tool.query("*"))) for tool in tools),
                    "max_event_loop_gap": max(ticks, default=0),
                }
                print(json.dumps(metrics, indent=2))
                assert not app.screen.query(MarkdownContent), "Collapsed output was parsed"
                assert metrics["tool_widgets"] <= len(tools) * 2
                assert tools[-1].query_one(ToolCallHeader) is header
                tools[-1].expanded = True
                await pilot.pause()
                assert tools[-1].query_one(MarkdownContent).source == text
                tools[-1].expanded = False
                await pilot.pause()
                assert not tools[-1].query(MarkdownContent)
                changed = dict(tools[-1].tool_call)
                changed["content"] = [{"type": "content", "content": {"type": "text", "text": "## Updated\n\nNew result"}}]
                await tools[-1].update_tool_call(changed)
                tools[-1].expanded = True
                await pilot.pause()
                assert "New result" in tools[-1].query_one(MarkdownContent).source
                conversation = app.screen.conversation
                for kind in (AgentResponse, AgentThought):
                    block = kind("First")
                    await conversation.post(block)
                    await block.append_fragment(" last fragment")
                    stream = block._stream
                    task = stream._task
                    if kind is AgentResponse:
                        conversation._agent_response = block
                    else:
                        conversation._agent_thought = block
                    conversation.new_block()
                    await pilot.pause()
                    assert block.source == "First last fragment"
                    assert task.done() and block._stream is None
                    await block.append_fragment(" after resume")
                    task = block._stream._task
                    await block.remove()
                    assert task.done(), "Removed Markdown retained a background updater"
                await conversation.contents.remove_children()
                for _ in range(8):
                    old = await conversation.post(AgentResponse(text))
                    await old.finish_stream()
                    await pilot.pause()
                assert all(len(list(child.query("*"))) < 150 for child in conversation.contents.children)
                assert all(child.source == text for child in conversation.contents.children)
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
