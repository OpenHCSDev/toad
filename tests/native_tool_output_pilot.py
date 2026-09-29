"""Installed Pi executes real Read/Edit/Bash tools through ACP and paints output."""

import asyncio
from importlib.resources import files
import json
from pathlib import Path
import threading

from l0a_native_installed_pilot import main as native_fixture, until
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from textual.selection import SELECT_ALL
from toad.widgets.tool_call import ToolCall
from toad.widgets.tool_content import TextContent, ToolCallDiff
from toad.widgets.patch_diff import PatchDiffView
from toad.widgets.worker_static import WorkerStatic

finished = threading.Event()


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def provider_reply(request, index):
    # Only the model is a deterministic loopback fixture. Tools, native journal,
    # owner/ACP transport, rendering workers and installed UI are the real path.
    if index <= 3:
        name, args = (
            ("read", {"path": "example.py"}),
            ("edit", {"path": "example.py", "oldText": "value = 1", "newText": "value = 2"}),
            ("bash", {"command": "printf '\\033[31mNATIVE_TOOL_TEXT\\033[0m\\n'"}),
        )[index - 1]
        names = [tool["function"]["name"] for tool in request.get("tools", ())]
        assert name in names, (name, names, sorted(request))
        return {"role": "assistant", "tool_calls": [{"index": 0, "id": f"native-tool-{index}",
                "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls"
    assert index == 4, "Native tool loop exceeded its declared three operations"
    assert finished.wait(35), "Installed tool output acceptance did not finish"
    return {"role": "assistant", "content": "NATIVE_TOOL_OUTPUT_COMPLETE"}, "stop"


def painted(app, tool, text):
    window = tool.query_ancestor("Window").content_region
    frame = "\n".join(strip.crop(window.x, window.right).text
                      for strip in app.screen._compositor.render_strips()[window.y:window.bottom])
    return text in frame and tool.region.overlaps(window)


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    project = Path(comms.registry.require("beta").worktree)
    source = "# Actual installed native tool output\nvalue = 1\n"
    (project / "example.py").write_text(source)
    view = app.screen.conversation
    sending = asyncio.create_task(agent.send_prompt("Execute the fixture tools and report completion"))
    try:
        await until(pilot, entered.is_set)
        release.set()
        await until(pilot, lambda: len(requests) == 4 or not comms.registry.require("beta").executing, 25)
        assert len(requests) == 4, (len(requests), [row.get("tools") for row in requests])
        await until(pilot, lambda: len(view.query(ToolCall)) == 3)
        tools = list(view.query(ToolCall))
        read, edit, bash = tools
        assert (project / "example.py").read_text() == source.replace("value = 1", "value = 2")
        for tool in tools:
            assert tool.tool_call["status"] == "completed", tool.tool_call

        read.set_expanded(True)
        read.scroll_visible(animate=False)
        await until(pilot, lambda: bool(read.query(WorkerStatic)))
        code = read.query_one(WorkerStatic)
        await asyncio.wait_for(code.wait_ready(), 15)
        assert "value = 1" in code.get_selection(SELECT_ALL)[0]
        await until(pilot, lambda: painted(app, read, "value = 1"))
        read.set_expanded(False)
        await pilot.pause()
        assert not read.query(WorkerStatic)

        edit.set_expanded(True)
        edit.scroll_visible(animate=False)
        diff = await wait_for_tool_diff(edit, pilot)
        assert diff.query_one(PatchDiffView).counts == (1, 1)
        await until(pilot, lambda: painted(app, edit, "value = 2"))
        edit.set_expanded(False)
        await pilot.pause()
        assert not edit.query(ToolCallDiff)
        edit.set_expanded(True)
        edit.scroll_visible(animate=False)
        await wait_for_tool_diff(edit, pilot)
        await until(pilot, lambda: painted(app, edit, "value = 2"))

        bash.set_expanded(True)
        bash.scroll_visible(animate=False)
        await until(pilot, lambda: bool(bash.query(TextContent)))
        text = bash.query_one(TextContent)
        assert "NATIVE_TOOL_TEXT" in text.get_selection(SELECT_ALL)[0]
        assert "\x1b" not in text.get_selection(SELECT_ALL)[0]
        await until(pilot, lambda: painted(app, bash, "NATIVE_TOOL_TEXT"))
        print("NATIVE_READ_EDIT_BASH_EXECUTED_COPIED_COLLAPSED_REOPENED_AND_PAINTED", flush=True)
        finished.set()
        await until(pilot, lambda: not comms.registry.require("beta").executing)
        assert len(requests) == 4
        await asyncio.wait_for(sending, 10)
    finally:
        release.set()
        finished.set()
        if not sending.done():
            sending.cancel()
        await asyncio.gather(sending, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance,
                              provider_reply=provider_reply))
