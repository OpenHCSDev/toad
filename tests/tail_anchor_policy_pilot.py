"""Tail intent needs no record geometry; reader transitions still preserve painted position."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from textual._compositor import ChopsUpdate, LayoutUpdate

from toad.widgets.note import Note

from history_scroll_frames_pilot import ScrollFrameApp
from toad.widgets.history_anchor import HistoryAnchor


class TailFrameApp(ScrollFrameApp):
    """Read the marker from published cells, never from unpainted DOM geometry."""

    def _display(self, screen, renderable):
        observed, self.observed = self.observed, None
        try:
            result = super()._display(screen, renderable)
        finally:
            self.observed = observed
        if observed is None or renderable is None or self._batch_count:
            return result
        marker, window, frames = observed
        region = window.scrollable_content_region
        if isinstance(renderable, ChopsUpdate):
            rows = ((y, "".join(strip.text for _, strip in
                              renderable._get_line_chops(y, max(x1, region.x),
                                                         min(x2, region.right))))
                    for y, x1, x2 in renderable.spans
                    if region.y <= y < region.bottom and x1 < region.right and x2 > region.x)
        elif isinstance(renderable, LayoutUpdate):
            rows = ((y, "".join(strip.text for strip in line))
                    for y, line in enumerate(renderable.strips, renderable.region.y)
                    if region.y <= y < region.bottom)
        else:
            raise AssertionError(f"Unobserved native publication: {type(renderable).__name__}")
        for y, text in rows:
            if str(marker.render()).splitlines()[0] in text:
                frames.append(y - window.content_region.y)
        return result


async def main():
    with TemporaryDirectory(prefix="toad-tail-anchor-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = TailFrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            view = app.selected_session.conversation
            window, contents = view.window, view.contents
            blocks = [Note(f"Record {index}\nsecond line") for index in range(80)]
            await contents.mount(*blocks)
            window.anchor()
            await pilot.pause()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            marker = blocks[20]
            assert marker not in app.screen._compositor.visible_widgets

            # A tail transaction's arbitrary source record can be offscreen.
            # Its position is not an input to bottom anchoring at any stage.
            with patch.object(HistoryAnchor, "_offset", side_effect=AssertionError(
                "Tail intent requested unnecessary record geometry"
            )):
                async with window.history_lock:
                    async with window.preserve_history(marker):
                        await contents.mount(Note("New tail record\nsecond line"))
                        await pilot.pause()
                assert window.follows_tail and window.scroll_y == window.max_scroll_y

            # Reader input can change the policy while admission is suspended.
            # Navigation changes reader intent before the held paint can move.
            # Derive the intended position from the original anchor geometry.
            async with window.history_lock:
                async with window.preserve_history(marker):
                    window.release_anchor()
                    window.scroll_to_widget(marker, animate=False, immediate=True)
                    await pilot.pause()
                    expected = HistoryAnchor._offset(marker, window) - window.scroll_y
                    frames = []
                    app.observed = marker, window, frames
                    await contents.mount(Note("Prepended one\nPrepended two"), before=0)
                    await pilot.pause()
            await pilot.pause()
            app.observed = None
            assert frames and set(frames) == {expected}, (expected, frames)
            assert not window.follows_tail

            # Returning to the tail likewise retires the record dependency.
            async with window.history_lock:
                async with window.preserve_history(marker):
                    window.anchor()
                    with patch.object(HistoryAnchor, "_offset", side_effect=AssertionError(
                        "Reader-to-tail transition retained a record geometry dependency"
                    )):
                        await contents.mount(Note("Latest tail record\nsecond line"))
                        await pilot.pause()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            assert window.history_anchor is None and not window.history_lock.locked()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tail anchor: no offscreen geometry; tail/reader transitions preserve painted intent")


if __name__ == "__main__":
    asyncio.run(main())
