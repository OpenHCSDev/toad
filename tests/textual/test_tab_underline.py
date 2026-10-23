"""Textual-facing: the underline painted beneath the tab strip marks the selected tab (label geometry and the bar's paint are the frontend's)."""

import pytest

from toad.navigation_context import NavigationContext
from toad.navigation_target import DirectTarget, channel_target
from toad.widgets.session_tabs import SessionLabel, SessionsTabs, Underline


def highlighted_columns(ui) -> list[int]:
    """Screen columns where the underline's highlight bar is painted."""
    app, _ = ui.textual
    underline = app.screen.query_one(Underline)
    color = underline.get_component_rich_style("underline--bar").color
    columns, x = [], 0
    for segment in app.screen._compositor.render_strips()[underline.region.y]:
        if (
            segment.style is not None
            and segment.style.color == color
            and "━" in segment.text
        ):
            columns.extend(range(x, x + segment.cell_length))
        x += segment.cell_length
    return columns


def label_columns(ui, identity) -> range:
    app, _ = ui.textual
    region = (
        app.screen.query_one(SessionsTabs)
        .query_one(f"#{identity}", SessionLabel)
        .region
    )
    return range(region.x, region.right)


def under(ui, identity) -> bool:
    columns, label = highlighted_columns(ui), label_columns(ui, identity)
    return bool(columns) and all(column in label for column in columns)


@pytest.mark.parametrize(
    "target",
    [DirectTarget("alpha"), channel_target("#team")],
    ids=["direct", "channel"],
)
async def test_underline_moves_to_a_tab_opened_from_the_sidebar_and_back(
    workspace, target
):
    workspace.thread("owner", "team")
    workspace.thread("alpha", "team")
    async with workspace.app(size=(140, 32)) as ui:
        app, _ = ui.textual
        first = ui.selected_tab
        await ui.until(
            lambda: under(ui, first), why="the underline under the first tab"
        )

        opened = await target.open(
            NavigationContext(app, first, app.project_dir, "owner")
        )
        await ui.until(
            lambda: ui.selected_tab == opened != first, why="the opened tab selected"
        )
        await ui.until(
            lambda: under(ui, opened),
            seconds=3,
            why=f"the underline under the opened tab; it is painted at {highlighted_columns(ui)[:1]}, "
            f"the tab is at {label_columns(ui, opened)}",
        )

        await ui.select_tab(first)
        await ui.until(
            lambda: under(ui, first),
            seconds=3,
            why="the underline back under the first tab",
        )
        await ui.close_tab(opened)
        await ui.until(
            lambda: under(ui, first),
            seconds=3,
            why="the underline under the remaining tab",
        )
