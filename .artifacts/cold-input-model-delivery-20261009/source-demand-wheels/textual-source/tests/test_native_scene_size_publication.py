"""Exercise scene transitions and size receipts through original native Apps."""

from textual import events
from textual.app import App
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.widgets import Static


async def test_scroll_intent_survives_layout_and_held_sources():
    from textual.screen import Screen

    history = VerticalScroll(Static("\n".join(str(n) for n in range(50))))

    class IntentScreen(Screen):
        held = False

        def __init__(self):
            super().__init__()
            self.admissions = []

        def compose(self):
            yield history

        def _layout_mutation_roots(self):
            return (history,) if self.held else ()

        def _prepare_compositor_refresh(self):
            return self._layout_mutation_roots()

        def _refresh_layout(self, size=None, scroll=False):
            self.admissions.append((
                scroll, self._has_actionable_layout_requests(self._held_layout_requests())
            ))
            super()._refresh_layout(size, scroll=scroll)

    class IntentApp(App):
        CSS = "VerticalScroll { height: 8; } Static { height: auto; }"

        def get_default_screen(self):
            return IntentScreen()

    app = IntentApp()
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        screen = app.screen
        original = screen._compositor.find_widget(history.children[0])
        screen.held = True
        screen.admissions.clear()
        history.refresh(layout=True)
        history.scroll_to(y=10, animate=False, immediate=True)
        history._check_refresh()
        await pilot.pause()
        assert (True, False) in screen.admissions
        assert screen._compositor.find_widget(history.children[0]) == original
        assert screen._layout_widgets
        screen.held = False
        screen.admissions.clear()
        history.refresh(layout=True)
        history.scroll_to(y=15, animate=False, immediate=True)
        history._check_refresh()
        await pilot.pause()
        assert (True, True) in screen.admissions
        assert not screen._layout_widgets
        assert screen._compositor.find_widget(history.children[0]).region.y == -15


class SizeReceipts:
    def on_resize(self, event: events.Resize) -> None:
        self.receipts.append((event.size, event.virtual_size, event.container_size))


async def test_screen_delivers_virtual_only_resize_after_child_mount():
    """A fixed outer region must still publish its changed child extent."""

    class History(SizeReceipts, VerticalScroll):
        def __init__(self):
            super().__init__(Static("FIRST", classes="row"))
            self.receipts = []

    history = History()

    class SizeApp(App):
        CSS = "History { width: 30; height: 8; } .row { height: 2; }"

        def compose(self):
            yield history

    async with SizeApp().run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        previous_size = history.outer_size
        previous_virtual = history.virtual_size
        history.receipts.clear()
        await history.mount(*(Static(f"ROW {i}", classes="row") for i in range(8)))
        await pilot.pause()
        assert history.outer_size == previous_size
        assert history.virtual_size.height > previous_virtual.height
        assert history.receipts[-1] == (
            history.outer_size,
            history.virtual_size,
            history.container_size,
        )


async def test_screen_delivers_container_only_resize_for_authored_line_surface():
    """Gutter changes publish native bounds without replacing authored extent."""

    class Lines(SizeReceipts, ScrollView):
        def __init__(self):
            super().__init__()
            self.receipts = []

    lines = Lines()
    authored = Size(80, 100)
    lines.virtual_size = authored

    class SizeApp(App):
        CSS = "Lines { width: 30; height: 8; }"

        def compose(self):
            yield lines

    async with SizeApp().run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        previous_size = lines.outer_size
        previous_container = lines.container_size
        assert lines.virtual_size == authored
        lines.receipts.clear()
        lines.styles.padding = 1
        await pilot.pause()
        assert lines.outer_size == previous_size
        assert lines.container_size == previous_container - Size(2, 2)
        assert lines.virtual_size == authored
        assert lines.receipts[-1] == (previous_size, authored, lines.container_size)
        assert lines.vertical_scrollbar.window_virtual_size == authored.height
        assert (
            lines.vertical_scrollbar.window_size
            == lines.container_size.height - lines.scrollbar_size_horizontal
        )


async def test_first_scroll_after_full_scene_does_not_damage_unchanged_chrome():
    """A missing viewport projection is not an empty committed paint scene."""

    class SceneApp(App):
        CSS = "#chrome { dock: top; height: 1; } .row { height: 2; }"

        def compose(self):
            yield Static("UNCHANGED CHROME", id="chrome")
            with VerticalScroll(id="history"):
                for index in range(30):
                    yield Static(f"ROW {index}", classes="row")

    app = SceneApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        screen = app.screen
        compositor = screen._compositor
        history = screen.query_one("#history", VerticalScroll)
        chrome = screen.query_one("#chrome")
        assert compositor._visible_map is None
        original_chrome = compositor.full_map[chrome]
        compositor._dirty_regions.clear()
        history.set_reactive(VerticalScroll.scroll_y, 4)
        exposed = compositor.reflow_visible(screen, app.size, retain_geometry=())
        assert chrome in exposed  # Exposure still conservatively initializes sizes.
        assert compositor._visible_map[chrome] == original_chrome
        assert compositor._dirty_regions
        assert app.size.region not in compositor._dirty_regions
        assert all(
            not region.overlaps(original_chrome.visible_region)
            for region in compositor._dirty_regions
        )

        # A later full scene must compare against the just-published viewport,
        # rather than the stale pre-scroll full geometry.
        visible_row = screen.query(".row")[3]
        previous = compositor._visible_map[visible_row].visible_region
        compositor._dirty_regions.clear()
        history.set_reactive(VerticalScroll.scroll_y, 0)
        compositor.reflow(screen, app.size)
        assert previous in compositor._dirty_regions
        assert compositor.full_map[chrome] == original_chrome


async def test_empty_committed_viewport_is_not_replaced_by_full_geometry():
    """A real empty visible scene remains the predecessor for full publication."""

    class SceneApp(App):
        def compose(self):
            yield Static("ORIGINAL")

    app = SceneApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        # A detached native root has no mounted scene members. No assigned map.
        compositor.reflow_visible(Static("DETACHED"), app.size, retain_geometry=())
        assert compositor._visible_map == {}
        assert compositor._published_map is compositor._visible_map
        compositor._dirty_regions.clear()
        compositor.reflow(app.screen, app.size)
        assert app.size.region in compositor._dirty_regions
