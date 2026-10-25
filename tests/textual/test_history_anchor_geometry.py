"""Textual-facing: reader positions work on the history window's scroll animation and the compositor's arranged layout."""

import pytest

from unittest.mock import patch

from textual.containers import VerticalGroup
from textual.widgets import Static

from toad.block_navigation import ConversationBlock
from toad.widgets.history_anchor import (
    BlockPosition, FragmentNotLoaded, FragmentPosition, HistoryWindow, ReaderPosition, RowPosition,
    TailPosition, UnreachedPosition,
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


async def test_layout_scroll_shifts_a_running_scroll_and_is_not_the_reader_moving(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        app, _pilot = ui.textual
        window = await long_window(ui)
        window.scroll_to(y=100, animate=False, immediate=True)
        window.scroll_to(y=200, duration=5, immediate=True)
        key = id(window), "scroll_y"
        animation = app.animator._animations[key]
        revision = window.scroll_revision
        with window.layout_scroll():
            window.scroll_y += 7
        assert app.animator._animations[key] is animation
        assert window.scroll_target_y == 207
        assert window.scroll_revision == revision

        # Placing a position is layout too: the running scroll continues from the new place.
        before = window.scroll_y
        with window.layout_scroll():
            assert RowPosition(50).place(window)
        assert window.scroll_y == 50
        assert app.animator._animations[key] is animation
        assert window.scroll_target_y == 207 + 50 - before
        assert window.scroll_revision == revision
        assert not window.follows_tail
        with window.layout_scroll():
            assert TailPosition().place(window)
        assert window.scroll_y == window.max_scroll_y
        assert window.scroll_revision == revision
        assert window.follows_tail


async def test_reading_a_row_reuses_the_committed_layout(workspace):
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
            assert window.row_of(marker) == 1999
            with window.layout_scroll():
                BlockPosition(marker, 1999, window.scroll_y).place(window)
            assert arrange.call_count == 0, "Reading a row remeasured an already committed layout"


async def test_a_record_layout_has_not_placed_has_no_row(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        window = await long_window(ui)
        window.release_anchor()
        marker = window.query_one("#record-1999")
        window.scroll_home(animate=False, immediate=True)
        await ui.step()
        await window.query_one("#geometry-records", VerticalGroup).mount(Static("Prepended"), before=0)
        await ui.step()
        # Layout places only what is visible or a declared geometry target; a kept position's widget is one of those.
        assert not tuple(window.placements((marker,)))
        with pytest.raises(LookupError, match="must be visible or declared geometry targets"):
            window.row_of(marker)


async def test_an_unloaded_fragment_cannot_be_placed_or_supply_geometry(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        window = await long_window(ui)
        window.release_anchor()
        position = FragmentPosition(123, 0, 1, part=0, block=0, occurrence=0)
        window.reader_position = UnreachedPosition(position)
        with pytest.raises(FragmentNotLoaded):
            position.page(window).location()
        assert not position.laid_out(window)
        assert not window.place_reader()
        with pytest.raises(LookupError, match="no drawn destination yet"):
            position.destination(window)
        assert window.history_geometry_targets() == ()
        assert window.reader_position == RowPosition(window.scroll_y)


class LiveBlock(ConversationBlock, Static):
    pass


async def test_a_live_block_hidden_since_the_last_frame_does_not_hold_the_reader(workspace):
    async with workspace.app(size=(100, 35)) as ui:
        window = await long_window(ui)
        block = LiveBlock("Draft", id="live-draft")
        await window.query_one("#geometry-records", VerticalGroup).mount(block)
        window.scroll_end(animate=False, immediate=True)
        await ui.step()
        window.release_anchor()
        screen = window.screen
        assert block in screen._compositor.published_widgets
        # The CLI draft ends: it hides, layout drops it, and the published frame still holds it.
        block.display = False
        screen._compositor.reflow(screen, screen.size, retain_geometry=screen._layout_geometry_targets())
        assert block in screen._compositor.published_widgets
        assert not tuple(window.placements((block,)))
        assert ReaderPosition.of(window) == RowPosition(window.scroll_y)
        window.reader_position = UnreachedPosition(BlockPosition(block, 0, window.scroll_y))
        assert not window.place_reader()
        assert window.reader_for_layout() == RowPosition(window.scroll_y)
