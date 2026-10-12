"""Textual-facing: reader positions and anchors work on the history window's scroll animation and the compositor's arranged layout."""

import pytest

from unittest.mock import patch

from textual.containers import VerticalGroup
from textual.widgets import Static

from toad.widgets.history_anchor import (
    HistoryAnchor, HistoryWindow, OffsetReaderPosition, TailReaderPosition, WindowPosition,
)


def records(count):
    rows = []
    for index in range(count):
        record = Static(f"Record {index}", id=f"record-{index}")
        record.styles.height = 1
        rows.append(record)
    return rows


async def long_window(ui):
    app, _pilot = ui.textual
    window = HistoryWindow(VerticalGroup(*records(2000), id="geometry-records"), id="geometry-window")
    window.styles.height = "1fr"
    await app.screen.mount(window)
    window.scroll_end(animate=False, immediate=True)
    await ui.step()
    return window


async def test_compensation_translates_a_running_scroll_and_a_restore_replaces_it(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, _pilot = ui.textual
        window = await long_window(ui)
        window.scroll_to(y=100, animate=False, immediate=True)
        window.scroll_to(y=200, duration=5, immediate=True)
        key = id(window), "scroll_y"
        animation = app.animator._animations[key]
        revision = window.scroll_revision
        with WindowPosition.geometry(window):
            window.scroll_y += 7
        assert app.animator._animations[key] is animation
        assert window.scroll_target_y == 207
        assert window.scroll_revision == revision

        OffsetReaderPosition(50, ()).restore(window)
        assert window.scroll_y == window.scroll_target_y == 50
        assert not app.animator.is_being_animated(window, "scroll_y")
        assert window.scroll_revision == revision
        assert not window.follows_tail
        window.scroll_to(y=150, duration=5, immediate=True)
        revision = window.scroll_revision
        TailReaderPosition().restore(window)
        assert window.scroll_y == window.scroll_target_y == window.max_scroll_y
        assert not app.animator.is_being_animated(window, "scroll_y")
        assert window.scroll_revision == revision
        assert window.follows_tail


async def test_reading_an_anchor_reuses_the_committed_layout(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        window = await long_window(ui)
        window.release_anchor()
        screen = window.screen
        marker = window.query_one("#record-1999")
        compositor = screen._compositor
        # The scroll -> prepend/full reflow sequence.
        compositor.reflow_visible(screen, screen.size, retain_geometry=screen._layout_geometry_targets())
        assert compositor._full_map_invalidated
        compositor.reflow(screen, screen.size, retain_geometry=screen._layout_geometry_targets())
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            anchor = HistoryAnchor.capture(marker, window)
            assert anchor.virtual_y == 1999
            anchor.restore(window)
            assert arrange.call_count == 0, "Anchor remeasured an already committed layout"


async def test_a_record_layout_has_not_placed_cannot_be_an_anchor(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        window = await long_window(ui)
        window.release_anchor()
        marker = window.query_one("#record-1999")
        window.scroll_home(animate=False, immediate=True)
        await ui.step()
        await window.query_one("#geometry-records", VerticalGroup).mount(Static("Prepended"), before=0)
        await ui.step()
        # Layout places only what is visible or a declared geometry target; an anchor must be one of those.
        with pytest.raises(LookupError, match="anchors must be visible or declared geometry targets"):
            HistoryAnchor.capture(marker, window)
