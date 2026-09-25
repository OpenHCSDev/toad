"""Goal collapse is local presentation; history and owner updates remain usable."""

import asyncio
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from agent_comms import Goal, GoalExecution, GoalExecutionState, GoalWaitTarget
from runtime_fixture import ToadApp
from textual.widgets import Static

from toad.screens.goal_details import GoalDetails
from toad.widgets.goal_bar import GoalBar, GoalControl, StandbyPulse


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-collapse-") as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            goal = Goal("OBJECTIVE " * 150, "goal", progress="PROGRESS", revision=29)
            view.goal = goal
            view.prompt.text = "Keep this draft"
            await pilot.pause()
            bar = view.query_one(GoalBar)
            history = bar.query_one("#goal-history", GoalControl)
            toggle = bar.query_one("#goal-collapse", GoalControl)
            header = bar.query_one(".goal-header", Static)
            controls = bar.query_one(".goal-controls")
            assert str(history.render()) == "History"
            assert str(toggle.render()) == "Collapse"
            assert controls.region.y > header.region.y
            assert await pilot.click(toggle)
            await pilot.pause()
            assert bar.collapsed and str(toggle.render()) == "Expand"
            assert controls.region.y == header.region.y
            assert controls.region.right <= header.region.x
            assert not bar.query_one(".goal-document").display
            assert not bar.query_one(".goal-execution-row").display
            assert bar.query_one_optional(".goal-scroll-hint") is None
            assert bar.region.height == 2, bar.region  # One row plus its separator.
            assert view.goal == goal and view.prompt.text == "Keep this draft"

            # Owner refreshes update the compact header without expanding it.
            view.goal = replace(goal, revision=30, progress="UPDATED_PROGRESS")
            await pilot.pause()
            assert bar.collapsed and "rev 30" in str(header.render())
            for width in (65, 58, 100):
                await pilot.resize_terminal(width, 38)
                await pilot.pause()
                assert not bar.query_one(".goal-document").display
                assert (controls.region.right <= header.region.x
                        or controls.region.bottom <= header.region.y)
                assert header.region.right <= bar.content_region.right
                assert bar.region.height <= 4, bar.region
                assert history.region.width >= len("History"), (width, history.region, controls.region)

            assert await pilot.click(history)
            await pilot.pause()
            assert isinstance(app.screen, GoalDetails)
            await pilot.press("escape")
            await pilot.pause()
            assert bar.collapsed and view.prompt.text == "Keep this draft"

            view.goal_execution = GoalExecution(
                GoalExecutionState.STANDBY, goal.id, (GoalWaitTarget("peer", 1.0),)
            )
            await pilot.pause()
            assert "Standby" in str(header.render())
            assert not bar.query_one(StandbyPulse).active
            assert await pilot.click(toggle)
            await pilot.pause()
            assert not bar.collapsed and str(toggle.render()) == "Collapse"
            assert controls.region.y > header.region.y
            assert bar.query_one(".goal-document").display
            assert bar.query_one(".goal-execution-row").display
            assert bar.query_one(StandbyPulse).active
            assert view.goal.progress == "UPDATED_PROGRESS"

            # An owner outage disables mutations, not this presentation toggle.
            view.goal_unavailable = True
            await pilot.pause()
            assert not toggle.disabled and history.disabled
            assert await pilot.click(toggle)
            await pilot.pause()
            assert bar.collapsed and "unavailable" in str(header.render())
            assert view.prompt.text == "Keep this draft"
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("goal collapse: compact left controls, history, live revision/standby, resize, outage and draft preserved")


if __name__ == "__main__":
    asyncio.run(main())
