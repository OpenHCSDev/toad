"""Absent goal documents must not rebuild offscreen geometry during resize."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms import Goal
from runtime_fixture import ToadApp
from textual.containers import VerticalScroll

from toad.widgets.goal_bar import GoalBar


async def main():
    with TemporaryDirectory(prefix="toad-goal-geometry-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            bar = view.query_one(GoalBar)

            def assert_no_full_layout(*updates):
                compositor = app.screen._compositor
                compositor.reflow(app.screen, app.size, visible_only=True)
                with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
                    for update in updates:
                        update()
                    assert arrange.call_count == 0, "Hidden goal measurement rebuilt the full widget tree"

            assert bar.goal is None and not bar.display
            assert_no_full_layout(bar.update_document_height, bar._update_control_layout)
            view.goal_unavailable = True
            await pilot.pause()
            assert bar.display and bar.goal is None
            assert_no_full_layout(bar.update_document_height)

            view.goal_unavailable = False
            view.goal = Goal("Visible wrapped goal text. " * 60, "geometry")
            await pilot.pause()
            document = bar.query_one(".goal-document", VerticalScroll)
            assert document.display and 1 < document.region.height <= app.size.height // 5
            bar.collapsed = True
            await pilot.pause()
            assert_no_full_layout(bar.update_document_height)
            bar.collapsed = False
            await pilot.resize_terminal(85, 30)
            await pilot.pause()
            assert document.display and 1 < document.region.height <= 6
            view.goal = None
            await pilot.pause()
            assert_no_full_layout(bar.update_document_height, bar._update_control_layout)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("goal geometry: hidden/absent document avoids full layout; shown, collapsed and resized goals remain bounded")


if __name__ == "__main__":
    asyncio.run(main())
