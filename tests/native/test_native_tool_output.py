"""The native agent runs real read, edit and bash tools; Toad draws each tool's output when expanded."""

import asyncio
import json
import threading

from support.native import ControlledProvider, native_session
from support.textual_steps import wait_for_tool_diff
from textual.selection import SELECT_ALL
from toad.widgets.patch_diff import PatchDiffView
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import TextContent, ToolCallDiff
from toad.widgets.worker_static import WorkerStatic

SOURCE = "# Native tool output\nvalue = 1\n"
CALLS = (
    ("read", {"path": "example.py"}),
    ("edit", {"path": "example.py", "oldText": "value = 1", "newText": "value = 2"}),
    ("bash", {"command": "printf '\\033[31mNATIVE_TOOL_TEXT\\033[0m\\n'"}),
)


async def test_read_edit_and_bash_output_is_drawn_and_survives_collapse(workspace, native_package):
    checked = threading.Event()

    def reply(request, number):
        if number <= len(CALLS):
            name, arguments = CALLS[number - 1]
            assert name in [tool["function"]["name"] for tool in request.get("tools", ())]
            return {"role": "assistant", "tool_calls": [{
                "index": 0, "id": f"native-tool-{number}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)}}]}, "tool_calls"
        assert number == len(CALLS) + 1, "The native agent asked for more than the three tool calls"
        assert checked.wait(35), "The test never finished checking the tool output"
        return {"role": "assistant", "content": "NATIVE_TOOL_OUTPUT_COMPLETE"}, "stop"

    (workspace.project / "example.py").write_text(SOURCE)
    async with native_session(workspace, native_package, provider=ControlledProvider(reply=reply)) as native:
        ui, agent, provider = native.ui, native.agent, native.provider
        view = ui.conversation

        def drawn(tool, text):
            return text in ui.painted(view.window) and tool.region.overlaps(view.window.content_region)

        sending = asyncio.create_task(agent.send_prompt("Execute the fixture tools and report completion"))
        try:
            await ui.until(lambda: len(provider.requests) == 4 or (provider.requests and not native.executing),
                           seconds=30, why="the three tool calls")
            assert len(provider.requests) == 4, len(provider.requests)
            await ui.until(lambda: len(view.query(ToolCall)) == 3, seconds=20, why="three tool call blocks")
            await ui.until(lambda: all(tool.tool_call.completed for tool in view.query(ToolCall)), seconds=20,
                           why="the tool calls to complete")
            read, edit, bash = view.query(ToolCall)
            assert (workspace.project / "example.py").read_text() == SOURCE.replace("value = 1", "value = 2")

            read.set_expanded(True)
            read.scroll_visible(animate=False)
            await ui.until(lambda: bool(read.query(WorkerStatic)), why="the read output")
            code = read.query_one(WorkerStatic)
            await asyncio.wait_for(code.wait_ready(), 15)
            assert "value = 1" in code.get_selection(SELECT_ALL)[0]
            await ui.until(lambda: drawn(read, "value = 1"), why="the read output on screen")
            read.set_expanded(False)
            await ui.step()
            assert not read.query(WorkerStatic)

            edit.set_expanded(True)
            edit.scroll_visible(animate=False)
            diff = await wait_for_tool_diff(ui, edit)
            assert diff.query_one(PatchDiffView).counts == (1, 1)
            await ui.until(lambda: drawn(edit, "value = 2"), why="the diff on screen")
            edit.set_expanded(False)
            await ui.step()
            assert not edit.query(ToolCallDiff)
            edit.set_expanded(True)
            edit.scroll_visible(animate=False)
            await wait_for_tool_diff(ui, edit)
            await ui.until(lambda: drawn(edit, "value = 2"), why="the diff after expanding again")

            bash.set_expanded(True)
            bash.scroll_visible(animate=False)
            await ui.until(lambda: bool(bash.query(TextContent)), why="the bash output")
            text = bash.query_one(TextContent)
            await asyncio.wait_for(text.wait_ready(), 15)
            assert "NATIVE_TOOL_TEXT" in text.get_selection(SELECT_ALL)[0]
            assert "\x1b" not in text.get_selection(SELECT_ALL)[0]
            await ui.until(lambda: drawn(bash, "NATIVE_TOOL_TEXT"), why="the bash output on screen")
            checked.set()
            await ui.until(lambda: not native.executing, seconds=20, why="the turn to finish")
            assert len(provider.requests) == 4
            await asyncio.wait_for(sending, 10)
        finally:
            checked.set()
            if not sending.done():
                sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
