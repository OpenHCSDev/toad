"""Animation visibility must not rebuild off-screen transcript geometry."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from toad.widgets.throbber import Throbber


class Probe(App):
    CSS = "Throbber { height: 1; } Static { height: 1; }"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="history"):
            yield Throbber(id="old-indicator")
            for index in range(2000):
                yield Static(f"Saved record {index}")
            yield Throbber(id="visible-indicator")
            yield Throbber(id="hidden-indicator")


async def main():
    app = Probe()
    async with app.run_test(size=(100, 35)) as pilot:
        hidden = app.query_one("#hidden-indicator", Throbber)
        old = app.query_one("#old-indicator", Throbber)
        visible = app.query_one("#visible-indicator", Throbber)
        for indicator in (hidden, old, visible):
            indicator.busy = True
            indicator.auto_refresh = None
        hidden.display = False
        history = app.query_one("#history", VerticalScroll)
        history.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        screen = app.screen
        compositor = screen._compositor
        compositor.reflow_visible(screen, screen.size)
        assert compositor._full_map_invalidated
        assert visible in compositor.visible_widgets
        assert old not in compositor.visible_widgets
        assert hidden not in compositor.visible_widgets

        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            with (
                patch.object(visible, "refresh") as repaint,
                patch.object(old, "refresh") as offscreen_repaint,
                patch.object(hidden, "refresh") as hidden_repaint,
            ):
                for _ in range(100):
                    hidden.automatic_refresh()
                    old.automatic_refresh()
                    visible.automatic_refresh()
                assert repaint.call_count == 100, "Visible animation stopped"
                offscreen_repaint.assert_not_called()
                hidden_repaint.assert_not_called()
            assert arrange.call_count == 0, "Animation rebuilt transcript geometry"
            # Positive control proves the original framework check hits the
            # expensive full-map fallback on precisely this scroll state.
            Widget.automatic_refresh(hidden)
            assert arrange.call_count == 1
            assert arrange.call_args.kwargs["visible_only"] is False

        await app.push_screen(Screen())
        await pilot.pause()
        with patch.object(visible, "refresh") as repaint:
            visible.automatic_refresh()
            repaint.assert_not_called()
        await app.pop_screen()
        await pilot.pause()
        with patch.object(visible, "refresh") as repaint:
            visible.automatic_refresh()
            repaint.assert_called_once()
    print("2000-record history: hidden/offscreen timers caused zero full-map rebuilds; visible and resumed animation still refresh")


if __name__ == "__main__":
    asyncio.run(main())
