"""Textual-facing: dragging the goal bar's separator (mouse capture, regions, bounds) with idle and busy separators."""

from dataclasses import replace

from agent_comms.goals import NoGoal
from textual.containers import VerticalScroll

from toad.widgets.goal_bar import GoalBar
from support.goals import published_goal

GOAL = published_goal("Long goal detail.\n" * 100, "resizing", revision=7)


async def shown_bar(ui):
    view = ui.conversation
    view.goal_display = GOAL
    view.prompt.text = "Keep draft while resizing"
    bar = view.query_one(GoalBar)
    document = bar.query_one(".goal-document", VerticalScroll)
    await ui.until(lambda: document.region.height > 1, why="the goal document")
    return view, bar, document


async def drag(ui, bar, widget, change):
    app, pilot = ui.textual
    x, y = widget.region.x + 3, widget.region.y
    end_y = max(1, min(app.size.height - 2, y - change))
    assert await pilot.mouse_down(widget, offset=(3, 0))
    assert app.mouse_captured is bar
    await pilot.hover(offset=(x, end_y))
    await pilot.mouse_up(offset=(x, end_y))
    await ui.step()
    assert app.mouse_captured is None and bar._resize_origin is None


async def test_idle_separator_drags_the_document_and_keeps_goal_and_draft(workspace):
    async with workspace.app(size=(110, 50)) as ui:
        app, pilot = ui.textual
        view, bar, document = await shown_bar(ui)
        initial = document.region.height
        normal = bar.styles.border_top
        assert await pilot.hover(bar, offset=(3, 0))
        await ui.until(lambda: bar.styles.border_top != normal, why="the separator highlighted on hover")
        await drag(ui, bar, bar, 4)
        assert document.region.height == initial + 4
        assert view.goal_display.snapshot == GOAL and view.prompt.text == "Keep draft while resizing"
        await drag(ui, bar, bar, -3)
        assert document.region.height == initial + 1


async def test_dragged_height_survives_a_new_revision_and_a_collapse_cycle(workspace):
    async with workspace.app(size=(110, 50)) as ui:
        app, pilot = ui.textual
        view, bar, document = await shown_bar(ui)
        await drag(ui, bar, bar, 3)
        resized = document.region.height
        view.goal_display = replace(GOAL, revision=8)
        await ui.step()
        assert document.region.height == resized
        await pilot.click("#goal-collapse")
        await ui.until(lambda: bar.collapsed, why="the bar collapsed")
        await pilot.click("#goal-collapse")
        await ui.until(lambda: not bar.collapsed, why="the bar expanded")
        assert document.region.height == resized


async def test_busy_separator_drags_within_bounds_and_follows_terminal_resize(workspace):
    async with workspace.app(size=(110, 50)) as ui:
        app, pilot = ui.textual
        view, bar, document = await shown_bar(ui)
        await drag(ui, bar, bar, 3)
        resized = document.region.height
        # During activity, the colored separator of the busy indicator owns this row.
        view.busy_count = 1
        view.turns.start_client()
        # The bar hands its edge to the throbber it is built with, directly above it.
        throbber = view.throbber
        await ui.until(lambda: throbber.busy, why="the busy indicator")
        await ui.until(lambda: not bar.styles.border_top[0], why="the separator row handed to the busy indicator")
        await drag(ui, bar, throbber, 2)
        assert document.region.height == resized + 2
        await drag(ui, bar, throbber, -100)
        assert document.region.height == 1
        await drag(ui, bar, throbber, 100)
        assert document.region.height <= app.size.height // 2
        await ui.resize(110, 30)
        assert document.region.height <= 15
        assert view.prompt.text == "Keep draft while resizing"


async def test_removing_the_goal_during_a_drag_releases_the_mouse(workspace):
    async with workspace.app(size=(110, 50)) as ui:
        app, pilot = ui.textual
        view, bar, document = await shown_bar(ui)
        assert await pilot.mouse_down(bar, offset=(3, 0))
        assert app.mouse_captured is bar
        view.goal_display = NoGoal()
        await ui.until(lambda: app.mouse_captured is None and not bar.display,
                       why="the mouse released and the bar hidden")
