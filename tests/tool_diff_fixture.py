"""Await real async diff content; a loading label is not a completed result."""

import asyncio

from toad.widgets.tool_call import ToolCallDiff


async def wait_for_tool_diff(tool, pilot):
    async with asyncio.timeout(10):
        while (diff := tool.query_one_optional(ToolCallDiff)) is None:
            await pilot.pause()
        await diff.prepared.wait()
        while not diff.query("PatchDiffView DiffCode, TextContent"):
            await pilot.pause()
        await pilot.pause()
    return diff
