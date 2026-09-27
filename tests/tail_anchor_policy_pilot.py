"""Tail intent needs no record geometry; reader transitions still preserve painted position."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from textual.widgets import Static

from history_scroll_frames_pilot import ScrollFrameApp
from toad.widgets.history_anchor import HistoryAnchor


async def main():
    with TemporaryDirectory(prefix="toad-tail-anchor-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ScrollFrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            view = app.screen.conversation
            window, contents = view.window, view.contents
            blocks = [Static(f"Record {index}\nsecond line") for index in range(80)]
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
                        await contents.mount(Static("New tail record\nsecond line"))
                        await pilot.pause()
                assert window.follows_tail and window.scroll_y == window.max_scroll_y

            # Reader input can change the policy while admission is suspended.
            # Capture the record's old committed coordinate before the prepend.
            async with window.history_lock:
                async with window.preserve_history(marker):
                    window.release_anchor()
                    window.scroll_to_widget(marker, animate=False, immediate=True)
                    await pilot.pause()
                    expected = marker.region.y - window.content_region.y
                    frames = []
                    app.observed = marker, window, frames
                    await contents.mount(Static("Prepended one\nPrepended two"), before=0)
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
                        await contents.mount(Static("Latest tail record\nsecond line"))
                        await pilot.pause()
            assert window.follows_tail and window.scroll_y == window.max_scroll_y
            assert window.history_anchor is None and not window.history_lock.locked()
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print("tail anchor: no offscreen geometry; tail/reader transitions preserve painted intent")


if __name__ == "__main__":
    asyncio.run(main())
