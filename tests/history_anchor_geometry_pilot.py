"""Reading a freshly measured anchor must not rebuild the full geometry map."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalGroup
from textual.widgets import Static

from toad.widgets.history_anchor import HistoryAnchor, HistoryWindow


class Probe(App):
    CSS = "Static { height: 1; }"

    def compose(self) -> ComposeResult:
        with HistoryWindow(id="window"):
            with VerticalGroup():
                for index in range(2000):
                    yield Static(f"Record {index}", id=f"record-{index}")


async def main():
    app = Probe()
    async with app.run_test(size=(100, 35)) as pilot:
        window = app.query_one(HistoryWindow)
        window.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        screen = app.screen
        marker = app.query_one("#record-1999")
        compositor = screen._compositor
        # Reproduce the actual scroll -> prepend/full reflow sequence.
        compositor.reflow_visible(screen, screen.size)
        assert compositor._full_map_invalidated
        compositor.reflow(screen, screen.size)
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            anchor = HistoryAnchor.capture(marker, window)
            assert anchor.virtual_y == 1999
            anchor.restore(window)
            assert arrange.call_count == 0, "Anchor remeasured an already committed layout"
        window.scroll_home(animate=False, immediate=True)
        await pilot.pause()
        await window.query_one(VerticalGroup).mount(Static("Prepended"), before=0)
        await pilot.pause()
        assert HistoryAnchor.capture(marker, window).virtual_y == 2000
    print("2000-record anchor: committed geometry reused; prepend and off-screen lookup remain correct")


if __name__ == "__main__":
    asyncio.run(main())
