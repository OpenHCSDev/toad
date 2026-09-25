"""Drag the existing goal separator without changing goal or composer state."""

import asyncio
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from agent_comms import Goal
from runtime_fixture import ToadApp
from textual.containers import VerticalScroll

from toad.widgets.goal_bar import GoalBar
from toad.widgets.throbber import Throbber


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-resize-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"), XDG_STATE_HOME=str(root / "state"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 50)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            goal = Goal("Long goal detail.\n" * 100, "resizing", revision=7)
            view.goal = goal
            view.prompt.text = "Keep draft while resizing"
            await pilot.pause()
            bar = view.query_one(GoalBar)
            document = bar.query_one(".goal-document", VerticalScroll)
            initial = document.region.height

            async def drag(widget, change):
                x, y = widget.region.x + 3, widget.region.y
                end_y = max(1, min(app.size.height - 2, y - change))
                assert await pilot.mouse_down(widget, offset=(3, 0))
                assert app.mouse_captured is bar
                await pilot.hover(offset=(x, end_y))
                await pilot.mouse_up(offset=(x, end_y))
                await pilot.pause()
                assert app.mouse_captured is None and bar._resize_origin is None

            normal = bar.styles.border_top
            assert await pilot.hover(bar, offset=(3, 0))
            await pilot.pause()
            assert bar.styles.border_top != normal
            await drag(bar, 4)
            assert document.region.height == initial + 4
            assert view.goal == goal and view.prompt.text == "Keep draft while resizing"
            await drag(bar, -3)
            resized = document.region.height
            assert resized == initial + 1
            view.goal = replace(goal, revision=8)
            await pilot.pause()
            assert document.region.height == resized
            await pilot.click("#goal-collapse")
            await pilot.pause()
            assert bar.collapsed
            await pilot.click("#goal-collapse")
            await pilot.pause()
            assert document.region.height == resized

            # During activity, the existing colored separator owns this row.
            view.busy_count = 1
            view.turn = "agent"
            await pilot.pause()
            throbber = view.query_one(Throbber)
            assert throbber.busy and not bar.styles.border_top[0]
            await drag(throbber, 2)
            assert document.region.height == resized + 2
            await drag(throbber, -100)
            assert document.region.height == 1
            await drag(throbber, 100)
            assert document.region.height <= app.size.height // 2
            await pilot.resize_terminal(110, 30)
            await pilot.pause()
            assert document.region.height <= 15
            assert view.prompt.text == "Keep draft while resizing"

            assert await pilot.mouse_down(throbber, offset=(3, 0))
            assert app.mouse_captured is bar
            view.goal = None
            await pilot.pause()
            assert app.mouse_captured is None and not bar.display
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("goal resize: idle/loading separator, capture, bounds, snapshot/collapse, resize, draft and cleanup")


if __name__ == "__main__":
    asyncio.run(main())
