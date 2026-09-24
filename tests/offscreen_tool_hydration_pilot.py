"""Autoexpanded tool output mounts only when its saved header becomes visible."""

import asyncio
from contextlib import nullcontext
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch as mock_patch

from agent_comms.tool_results import ToolDiff, tool_result_content
from runtime_fixture import ToadApp
from tool_diff_fixture import wait_for_tool_diff
from toad.widgets.tool_call import ToolCall, ToolCallDiff


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-lazy-visible-tools-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            app.settings.set("tools.expand", "always")
            patch = ("--- first.py\n+++ first.py\n@@ -1,2 +1,2 @@\n context\n-old\n+new\n")
            tools = [ToolCall({"toolCallId": f"edit-{index}", "title": f"Edit file {index}",
                "kind": "edit", "status": "completed",
                "content": tool_result_content(f"edit-{index}", "done", ToolDiff(patch))})
                for index in range(28)]
            eager = os.environ.get("TOAD_BENCH_EAGER_TOOLS") == "1"
            visual_policy = mock_patch.object(ToolCall, "_visible_in_window", return_value=True) if eager else nullcontext()
            with visual_policy:
                start, cpu = time.perf_counter(), time.process_time()
                await app.screen.conversation.contents.mount(*tools)
                app.screen.conversation.window.anchor()
                await pilot.pause()
                initial_ms = (time.perf_counter() - start) * 1000
                initial_cpu_ms = (time.process_time() - cpu) * 1000
            first, last = tools[0], tools[-1]
            mounted = sum(bool(tool.query(ToolCallDiff)) for tool in tools)
            initial_widgets = len(list(app.screen.walk_children()))
            if not eager:
                assert first.expanded and not first.query(ToolCallDiff)
                assert mounted < len(tools) // 2
            else:
                assert mounted == len(tools)
            last.scroll_visible(animate=False)
            await pilot.pause()
            await wait_for_tool_diff(last, pilot)
            assert last.query_one(ToolCallDiff).patch == patch
            first.scroll_visible(animate=False)
            await pilot.pause()
            await wait_for_tool_diff(first, pilot)
            assert first.query_one(ToolCallDiff).patch == patch
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print({"autoexpanded": len(tools), "eager_policy": eager, "initial_widgets": initial_widgets,
           "initial_render_ms": round(initial_ms, 1), "initial_cpu_ms": round(initial_cpu_ms, 1),
           "mounted_before_scroll": mounted,
           "deferred": len(tools) - mounted, "hydrated_on_scroll": True})


if __name__ == "__main__":
    asyncio.run(main())
