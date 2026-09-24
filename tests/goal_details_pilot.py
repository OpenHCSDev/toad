"""Long objectives and progress remain readable without disturbing the composer."""

import asyncio
import os
import tempfile
from pathlib import Path

from agent_comms import Goal
from textual.containers import VerticalScroll
from toad.app import ToadApp
from toad.screens.goal_details import GoalDetails


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-goal-details-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"), XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"), AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            goal = Goal("GOAL_BEGIN\n" + "Long objective with important details.\n" * 100,
                        "goal", progress="Progress details.\n" * 80 + "PROGRESS_END")
            conversation.goal = goal
            conversation.prompt.text = "Keep this draft"
            await pilot.pause()
            await pilot.click("#goal-expand")
            await pilot.pause()
            assert isinstance(app.screen, GoalDetails)
            assert app.screen.query_one(VerticalScroll).max_scroll_y > 0
            for width, height in ((100, 35), (65, 18)):
                await pilot.resize_terminal(width, height)
                app.screen.query_one(VerticalScroll).focus()
                await pilot.press("end")
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "PROGRESS_END" in frame, frame
                await pilot.press("home")
                await pilot.pause()
                frame = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
                assert "GOAL_BEGIN" in frame, frame
            await pilot.press("escape")
            await pilot.pause()
            assert conversation.goal == goal
            assert conversation.prompt.text == "Keep this draft"
    print("goal details: full objective/progress scroll at narrow sizes; goal and draft preserved")


if __name__ == "__main__":
    asyncio.run(main())
