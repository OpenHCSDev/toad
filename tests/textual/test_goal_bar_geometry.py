"""Textual-facing: the goal bar's measurements must not trigger a full compositor layout, and its document stays bounded."""

from unittest.mock import patch

from agent_comms.goals import NoGoal
from agent_comms.ui_model.goal import GoalUnavailable
from textual.containers import VerticalScroll

from toad.widgets.goal_bar import GoalBar
from support.goals import published_goal


def assert_no_full_layout(app, *updates):
    compositor = app.screen._compositor
    compositor.reflow(app.screen, app.size, visible_only=True)
    with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
        for update in updates:
            update()
        assert arrange.call_count == 0, "Hidden goal measurement rebuilt the full widget tree"


async def test_absent_goal_document_never_rebuilds_the_whole_layout(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, pilot = ui.textual
        view = ui.conversation
        bar = view.query_one(GoalBar)
        assert bar.goal_display.snapshot == NoGoal() and not bar.display
        assert_no_full_layout(app, bar.update_document_height, bar._update_control_layout)
        view.goal_display = GoalUnavailable(view.goal_display.snapshot)
        await ui.until(lambda: bar.display, why="the unavailable bar shown")
        assert bar.goal_display.snapshot == NoGoal()
        assert_no_full_layout(app, bar.update_document_height)


async def test_shown_collapsed_and_resized_goal_document_stays_bounded(workspace):
    async with workspace.app(size=(110, 40)) as ui:
        app, pilot = ui.textual
        view = ui.conversation
        bar = view.query_one(GoalBar)
        view.goal_display = published_goal("Visible wrapped goal text. " * 60, "geometry")
        document = bar.query_one(".goal-document", VerticalScroll)
        await ui.until(lambda: document.display and document.region.height > 1, why="the goal document laid out")
        assert 1 < document.region.height <= app.size.height // 5
        bar.collapsed = True
        await ui.step()
        assert_no_full_layout(app, bar.update_document_height)
        bar.collapsed = False
        await ui.resize(85, 30)
        assert document.display and 1 < document.region.height <= 6
        view.goal_display = NoGoal()
        await ui.until(lambda: not bar.display, why="the bar hidden once the goal is gone")
        assert_no_full_layout(app, bar.update_document_height, bar._update_control_layout)
