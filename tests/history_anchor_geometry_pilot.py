"""Reading a freshly measured anchor must not rebuild the full geometry map."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime_fixture import ToadApp
from textual.containers import VerticalGroup
from textual.widgets import Static

from toad.widgets.history_anchor import (
    HistoryAnchor, HistoryWindow, OffsetReaderPosition, TailReaderPosition, WindowRestoration,
)


class Probe(ToadApp):
    CSS = "#geometry-window { height: 1fr; } #geometry-records > Static { height: 1; }"


async def exercise(app):
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        window = HistoryWindow(VerticalGroup(*(
            Static(f"Record {index}", id=f"record-{index}") for index in range(2000)
        ), id="geometry-records"), id="geometry-window")
        await app.screen.mount(window)
        window.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        # Compensation translates the same running curve. A saved reader
        # restore deliberately replaces it and must retain its new destination.
        window.scroll_to(y=100, animate=False, immediate=True)
        window.scroll_to(y=200, duration=5, immediate=True)
        key = id(window), "scroll_y"
        animation = app.animator._animations[key]
        revision = window.scroll_revision
        with WindowRestoration.geometry(window):
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
        await pilot.pause()
        # The committed-record lookup below is an offset-reader case, separate
        # from the explicit tail restoration just exercised.
        window.release_anchor()
        screen = window.screen
        marker = window.query_one("#record-1999")
        compositor = screen._compositor
        # Reproduce the actual scroll -> prepend/full reflow sequence.
        compositor.reflow_visible(screen, screen.size, retain_geometry=screen._layout_geometry_targets())
        assert compositor._full_map_invalidated
        compositor.reflow(screen, screen.size, retain_geometry=screen._layout_geometry_targets())
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            anchor = HistoryAnchor.capture(marker, window)
            assert anchor.virtual_y == 1999
            anchor.restore(window)
            assert arrange.call_count == 0, "Anchor remeasured an already committed layout"
        window.scroll_home(animate=False, immediate=True)
        await pilot.pause()
        await window.query_one("#geometry-records", VerticalGroup).mount(Static("Prepended"), before=0)
        await pilot.pause()
        assert HistoryAnchor.capture(marker, window).virtual_y == 2000
    print("2000-record anchor: committed geometry reused; prepend and off-screen lookup remain correct")


async def main():
    with TemporaryDirectory(prefix="reader-motion-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        await exercise(Probe(project_dir=str(root)))
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
