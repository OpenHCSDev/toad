from textual.app import App
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static


class ViewportScreen(Screen):
    CSS = "#side { width: 20; } #history { width: 1fr; } Static { height: auto; }"

    def _use_viewport_layout(self):
        return True

    def compose(self):
        with Horizontal():
            yield Static("sidebar", id="side")
            with VerticalScroll(id="history"):
                for index in range(150):
                    yield Static(f"Row {index}: " + "wrapped text " * 5, id=f"row-{index}")


def rendered(screen):
    return tuple(tuple(strip) for strip in screen._compositor.render_strips())


async def test_viewport_layout_matches_full_geometry_and_render_after_changes():
    app = App()
    async with app.run_test(size=(90, 24)) as pilot:
        screen = ViewportScreen()
        await app.push_screen(screen)
        await pilot.pause()
        history = screen.query_one("#history", VerticalScroll)
        sidebar = screen.query_one("#side", Static)
        for width, scroll in ((20, 0), (3, 0), (20, 150), (3, 280), (28, 40)):
            sidebar.styles.width = width
            history.scroll_to(y=scroll, animate=False, immediate=True)
            await pilot.pause()
            actual = rendered(screen)
            visible = dict(screen._compositor.visible_widgets)
            # Independent native full-layout oracle on the same source tree.
            screen._compositor.reflow(screen, app.size)
            assert rendered(screen) == actual
            assert screen._compositor.visible_widgets == visible

        # An offscreen geometry query must be fresh, and later exposure must
        # deliver the newly measured dimensions to the actual widget.
        hidden = screen.query_one("#row-149", Static)
        sidebar.styles.width = 7
        await pilot.pause()
        region = hidden.region
        history.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        assert hidden.size.width == region.width
        hidden.update("changed " * 80)
        await pilot.pause()
        actual = rendered(screen)
        screen._compositor.reflow(screen, app.size)
        assert rendered(screen) == actual
        await pilot.resize_terminal(65, 29)
        await pilot.pause()
        actual = rendered(screen)
        screen._compositor.reflow(screen, app.size)
        assert rendered(screen) == actual
