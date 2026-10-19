"""Textual-facing: the goal bar's compact layout, region sizes and click targets when collapsed or narrow."""

from dataclasses import replace

from agent_comms.goal_presentation import GoalExecution, GoalExecutionState, GoalWaitTarget
from agent_comms.thread_identity import RecordedThreadIncarnation
from agent_comms.ui_model.goal import GoalUnavailable
from textual.widgets import Static

from toad.screens.goal_details import GoalDetails
from toad.widgets.goal_bar import GoalBar, GoalControl, StandbyPulse
from support.goals import published_goal

GOAL = published_goal("OBJECTIVE " * 150, "goal", progress="PROGRESS", revision=29)


async def shown_bar(ui):
    view = ui.conversation
    view.goal_display = GOAL
    view.prompt.text = "Keep this draft"
    await ui.step()
    bar = view.query_one(GoalBar)
    return view, bar, bar.query_one("#goal-history", GoalControl), bar.query_one("#goal-collapse", GoalControl), \
        bar.query_one(".goal-header", Static), bar.query_one(".goal-controls")


async def test_collapsing_moves_controls_beside_the_header_and_keeps_goal_and_draft(workspace):
    async with workspace.app(size=(100, 38)) as ui:
        app, pilot = ui.textual
        view, bar, history, toggle, header, controls = await shown_bar(ui)
        assert str(history.render()) == "History"
        assert str(toggle.render()) == "Collapse"
        assert controls.region.y > header.region.y
        assert await pilot.click(toggle)
        await ui.step()
        assert bar.collapsed and str(toggle.render()) == "Expand"
        assert controls.region.y == header.region.y
        assert controls.region.right <= header.region.x
        assert not bar.query_one(".goal-document").display
        assert not bar.query_one(".goal-execution-row").display
        assert bar.query_one_optional(".goal-scroll-hint") is None
        assert bar.region.height == 2, bar.region  # One row plus its separator.
        assert view.goal_display.snapshot == GOAL and view.prompt.text == "Keep this draft"


async def test_collapsed_header_follows_owner_updates_and_stays_usable_when_narrow(workspace):
    async with workspace.app(size=(100, 38)) as ui:
        app, pilot = ui.textual
        view, bar, history, toggle, header, controls = await shown_bar(ui)
        assert await pilot.click(toggle)
        await ui.step()
        view.goal_display = replace(GOAL, revision=30, progress="UPDATED_PROGRESS")
        await ui.until(lambda: "rev 30" in str(header.render()), why="the revision in the collapsed header")
        assert bar.collapsed
        for width in (65, 58, 100):
            await ui.resize(width, 38)
            assert not bar.query_one(".goal-document").display
            assert controls.region.right <= header.region.x or controls.region.bottom <= header.region.y
            assert header.region.right <= bar.content_region.right
            assert bar.region.height <= 4, bar.region
            assert history.region.width >= len("History"), (width, history.region, controls.region)


async def test_history_control_opens_details_from_a_collapsed_bar_and_returns_to_it(workspace):
    async with workspace.app(size=(100, 38)) as ui:
        app, pilot = ui.textual
        view, bar, history, toggle, header, controls = await shown_bar(ui)
        assert await pilot.click(toggle)
        await ui.step()
        assert await pilot.click(history)
        await ui.until(lambda: isinstance(app.screen, GoalDetails), why="the goal details screen")
        await ui.press("escape")
        assert bar.collapsed and view.prompt.text == "Keep this draft"


async def test_expanding_shows_standby_and_the_latest_progress(workspace):
    async with workspace.app(size=(100, 38)) as ui:
        app, pilot = ui.textual
        view, bar, history, toggle, header, controls = await shown_bar(ui)
        assert await pilot.click(toggle)
        await ui.step()
        view.goal_display = replace(GOAL, revision=30, progress="UPDATED_PROGRESS")
        view.goal_execution = GoalExecution(GoalExecutionState.STANDBY, GOAL.id, (GoalWaitTarget(RecordedThreadIncarnation("peer", 1.0)),))
        await ui.until(lambda: "Standby" in str(header.render()), why="Standby in the collapsed header")
        assert not bar.query_one(StandbyPulse).active
        assert await pilot.click(toggle)
        await ui.step()
        assert not bar.collapsed and str(toggle.render()) == "Collapse"
        assert controls.region.y > header.region.y
        assert bar.query_one(".goal-document").display
        assert bar.query_one(".goal-execution-row").display
        assert bar.query_one(StandbyPulse).active
        assert view.goal_display.snapshot.progress == "UPDATED_PROGRESS"


async def test_owner_outage_disables_history_but_not_collapse(workspace):
    async with workspace.app(size=(100, 38)) as ui:
        app, pilot = ui.textual
        view, bar, history, toggle, header, controls = await shown_bar(ui)
        view.goal_display = GoalUnavailable(view.goal_display.snapshot)
        await ui.until(lambda: history.disabled, why="the history control disabled")
        assert not toggle.disabled
        assert await pilot.click(toggle)
        await ui.until(lambda: bar.collapsed and "unavailable" in str(header.render()),
                       why="a collapsed header that says the owner is unavailable")
        assert view.prompt.text == "Keep this draft"
