"""Goal separators follow the actual loading and delivery-controls presentation."""

import asyncio
import os
from pathlib import Path
import tempfile

from agent_comms import Goal
from runtime_fixture import ToadApp
from toad.widgets.goal_bar import GoalBar
from toad.widgets.throbber import Throbber


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-separators-") as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                          XDG_STATE_HOME=str(root / "state"), AGENT_COMMS_ROOT=str(root / "wire"))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            goal = view.query_one(GoalBar)
            bar = view.query_one(Throbber)
            prompt = view.prompt
            draft = "Keep this draft while separator edges move"
            prompt.text = draft
            view.goal = Goal("Verify layout", "separator-test", status="paused", progress="Working on presentation")
            cases = [
                (0, "client", True, "solid", "", "idle"),
                (1, "agent", True, "", "solid", "loading-and-queue"),
                (1, "agent", False, "", "", "loading-without-queue"),
                (0, "client", True, "solid", "", "back-to-idle"),
            ]
            for busy, turn, supported, top, bottom, label in cases:
                view.busy_count = busy
                view.turn = turn
                view.queue_supported = supported
                await pilot.pause()
                assert bar.busy == bool(busy)
                assert bool(goal.styles.border_top[0]) == bool(top), (label, goal.styles.border_top)
                assert bool(goal.styles.border_bottom[0]) == bool(bottom), (label, goal.styles.border_bottom)
                if bottom:
                    assert goal.styles.border_bottom == goal.styles.base.border_top
                    controls = prompt.query_one(".delivery-controls")
                    assert controls.display
                    assert goal.query_one("#goal-clear").region.bottom <= goal.region.bottom - 1
                    assert controls.region.y >= goal.region.bottom
                    lines = app.screen._compositor.render_strips()
                    separator = lines[goal.region.bottom - 1].text[goal.region.x:goal.region.right]
                    assert "─" in separator, (label, separator)
                if busy:
                    assert goal.query_one(".goal-summary").region.y == goal.region.y
                assert prompt.text == draft

            view.goal = None
            view.busy_count = 1
            view.turn = "agent"
            await pilot.pause()
            assert not goal.display
            assert goal not in app.screen._compositor.visible_widgets
            assert prompt.query_one(".delivery-controls").display
            assert prompt.text == draft
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("goal separators: idle top, loading replaces top, queue-only bottom, hidden goal, draft preserved")


if __name__ == "__main__":
    asyncio.run(main())
