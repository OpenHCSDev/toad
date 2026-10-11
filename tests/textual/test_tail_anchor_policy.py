"""Textual-facing: the history window's anchors depend on Textual's compositor geometry and published cells.

Tail intent needs no record geometry; reader transitions still keep the painted position.
"""

from unittest.mock import patch

from textual._compositor import ChopsUpdate, LayoutUpdate

from toad.widgets.history_anchor import HistoryAnchor
from toad.widgets.note import Note


def watch_marker_rows(app, window, marker):
    """Record the window row of `marker`'s first line in every published frame; returns (rows, stop)."""
    rows_seen = []
    display = app._display

    def record(screen, renderable):
        result = display(screen, renderable)
        if renderable is None or app._batch_count:
            return result
        region = window.scrollable_content_region
        if isinstance(renderable, ChopsUpdate):
            rows = ((y, "".join(strip.text for _, strip in
                                renderable._get_line_chops(y, max(x1, region.x), min(x2, region.right))))
                    for y, x1, x2 in renderable.spans
                    if region.y <= y < region.bottom and x1 < region.right and x2 > region.x)
        elif isinstance(renderable, LayoutUpdate):
            rows = ((y, "".join(strip.text for strip in line))
                    for y, line in enumerate(renderable.strips, renderable.region.y)
                    if region.y <= y < region.bottom)
        else:
            raise AssertionError(f"Unobserved publication: {type(renderable).__name__}")
        for y, text in rows:
            if str(marker.render()).splitlines()[0] in text:
                rows_seen.append(y - window.content_region.y)
        return result

    app._display = record
    return rows_seen, lambda: setattr(app, "_display", display)


async def test_tail_intent_needs_no_record_geometry_and_reader_intent_keeps_the_painted_row(workspace):
    async with workspace.app(size=(100, 32)) as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        window, contents = view.window, view.contents
        blocks = [Note(f"Record {index}\nsecond line") for index in range(80)]
        await contents.mount(*blocks)
        window.anchor()
        await ui.until(lambda: window.follows_tail and window.scroll_y == window.max_scroll_y, why="the tail")
        marker = blocks[20]
        assert marker not in app.screen._compositor.visible_widgets

        # A tail transaction's record can be offscreen; its position is not an input to bottom anchoring.
        with patch.object(HistoryAnchor, "_offset", side_effect=AssertionError(
                "Tail intent requested unnecessary record geometry")):
            async with window.history_lock:
                async with window.preserve_history(marker):
                    await contents.mount(Note("New tail record\nsecond line"))
                    await ui.step()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y

        # Reader input can change the policy while admission is suspended: the intended
        # position derives from the anchor's geometry before the held paint.
        async with window.history_lock:
            async with window.preserve_history(marker):
                window.release_anchor()
                window.scroll_to_widget(marker, animate=False, immediate=True)
                await ui.step()
                expected = HistoryAnchor._offset(marker, window) - window.scroll_y
                frames, stop = watch_marker_rows(app, window, marker)
                await contents.mount(Note("Prepended one\nPrepended two"), before=0)
                await ui.step()
        await ui.step()
        stop()
        assert frames and set(frames) == {expected}, (expected, frames)
        assert not window.follows_tail

        # Returning to the tail likewise retires the record dependency.
        async with window.history_lock:
            async with window.preserve_history(marker):
                window.anchor()
                with patch.object(HistoryAnchor, "_offset", side_effect=AssertionError(
                        "Reader-to-tail transition retained a record geometry dependency")):
                    await contents.mount(Note("Latest tail record\nsecond line"))
                    await ui.step()
        assert window.follows_tail and window.scroll_y == window.max_scroll_y
        assert window.history_restoration is None and not window.history_lock.locked()
