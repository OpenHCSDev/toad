"""The animation clock's visibility rule must not rebuild off-screen transcript geometry."""

import asyncio
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from toad.textual_colours import ThemedApp
from toad.widgets.throbber import Throbber


class Probe(ThemedApp, App):
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
        clock = app.colours.clock
        for indicator in (hidden, old, visible):
            indicator.busy = True
        assert set(clock.running) == {hidden, old, visible}
        # The pilot ticks the clock itself.
        app.colours._schedule(None)
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

        def tick() -> None:
            for animation in clock.running.values():
                animation.due = 0.0
            clock.tick()

        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            with (
                patch.object(visible, "refresh") as repaint,
                patch.object(old, "refresh") as offscreen_repaint,
                patch.object(hidden, "refresh") as hidden_repaint,
            ):
                for _ in range(100):
                    tick()
                assert repaint.call_count == 100, "Visible animation stopped"
                offscreen_repaint.assert_not_called()
                hidden_repaint.assert_not_called()
            assert arrange.call_count == 0, "Animation rebuilt transcript geometry"
            # Textual's own timer refresh reads the committed layout too: it
            # must not rebuild the full map on this scroll state either.
            Widget.automatic_refresh(hidden)
            assert arrange.call_count == 0

        await app.push_screen(Screen())
        await pilot.pause()
        with patch.object(visible, "refresh") as repaint:
            tick()
            repaint.assert_not_called()
        await app.pop_screen()
        await pilot.pause()
        with patch.object(visible, "refresh") as repaint:
            tick()
            repaint.assert_called_once()
    print("2000-record history: hidden/offscreen animations caused zero full-map rebuilds; visible and resumed animation still repaint")


if __name__ == "__main__":
    asyncio.run(main())
