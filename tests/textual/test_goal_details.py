"""Textual-facing: the goal details screen's scroll container and the frame it paints at narrow sizes."""

from agent_comms.goals import Goal
from agent_comms.ui_model.goal import GoalDisplay
from textual.containers import VerticalScroll

from toad.screens.goal_details import GoalDetails


async def test_long_objective_and_progress_scroll_fully_at_narrow_sizes(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, pilot = ui.textual
        conversation = ui.conversation
        goal = Goal("GOAL_BEGIN\n" + "Long objective with important details.\n" * 100,
                    "goal", progress="Progress details.\n" * 80 + "PROGRESS_END")
        conversation.goal_display = GoalDisplay.current(goal)
        conversation.prompt.text = "Keep this draft"
        await ui.until_shows("History")
        await ui.click("History")
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="the goal details screen")
        assert app.screen.query_one(VerticalScroll).max_scroll_y > 0
        for width, height in ((100, 35), (65, 18)):
            await ui.resize(width, height)
            app.screen.query_one(VerticalScroll).focus()
            await ui.press("end")
            await ui.until_shows("PROGRESS_END")
            await ui.press("home")
            await ui.until_shows("GOAL_BEGIN")
        await ui.press("escape")
        assert conversation.goal_display.snapshot == goal
        assert conversation.prompt.text == "Keep this draft"
