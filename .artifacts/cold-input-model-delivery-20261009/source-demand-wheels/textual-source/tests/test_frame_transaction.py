import asyncio

import pytest

from textual.app import App
from textual.containers import Vertical
from textual.geometry import Region
from textual.screen import Screen
from textual.widgets import Static


class FrameScreen(Screen):
    def __init__(self):
        super().__init__()
        self.preparations = []
        self.publications = []

    def _layout_mutation_roots(self):
        return tuple(root for root in self.query(Vertical) if root.lock.is_locked)

    def _prepare_compositor_refresh(self):
        roots = self._layout_mutation_roots()
        self.preparations.append(roots)
        return roots

    def _on_frame_published(self, roots):
        self.publications.append(roots)


class FrameApp(App):
    CSS = "#holder { width: 20; height: 8; } #sidebar { dock: right; width: 20; }"

    def get_default_screen(self):
        return FrameScreen()

    def compose(self):
        with Vertical(id="holder"):
            yield Static("first", id="content")
        yield Static("SIDEBAR", id="sidebar")

    def __init__(self):
        super().__init__()
        self.updates = []

    def _display(self, screen, renderable):
        if renderable is not None:
            self.updates.append(renderable)
        super()._display(screen, renderable)


async def test_layout_and_full_repaint_commit_one_compositor_frame():
    app = FrameApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        app.query_one("#content", Static).update("replacement\nsecond row")
        screen.refresh(layout=True)
        screen.preparations.clear()
        app.updates.clear()
        screen._on_timer_update()
        assert screen.preparations == [()]
        assert len(app.updates) == 1
        await pilot.pause()
        text = "\n".join(strip.text for strip in screen._compositor.render_strips())
        assert "replacement" in text and "second row" in text


@pytest.mark.parametrize("scroll", [False, True])
async def test_timer_publishes_after_layout_signal_and_retains_held_damage(scroll):
    from textual._compositor import ChopsUpdate

    app = FrameApp()
    scene_done, sidebar_done = asyncio.Event(), asyncio.Event()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        screen = app.screen
        holder = app.query_one("#holder", Vertical)
        sidebar = app.query_one("#sidebar", Static)
        original = screen._compositor.find_widget(holder)
        before = screen._compositor.find_widget(app.query_one("#content"))

        def layout_completed(_screen):
            # This synchronous subscriber changes actual style before the
            # publication decision. It also requests a later independent
            # layout, which must not be consumed by this timer's earlier intent.
            sidebar.styles.color = "red"
            screen.refresh(layout=True)

        screen.screen_layout_refresh_signal.subscribe(app, layout_completed, immediate=True)
        async with holder.lock:
            app.call_after_refresh(scene_done.set)
            sidebar.call_after_refresh(sidebar_done.set)
            screen._scroll_required = scroll
            screen.refresh(layout=not scroll)
            screen.preparations.clear()
            screen.publications.clear()
            app.updates.clear()
            screen._on_timer_update()

            assert screen.preparations == [(holder,)]
            assert screen.publications == [(holder,)]
            assert len(app.updates) == 1
            update = app.updates[0]
            assert isinstance(update, ChopsUpdate)
            assert all(not Region(x1, y, x2 - x1, 1).overlaps(original.visible_region)
                       for y, x1, x2 in ChopsUpdate._span_cuts(update.spans, update.cuts, 0))
            rendered = update.render_segments(app.console)
            assert "SIDEBAR" in rendered and "first" not in rendered
            assert screen._compositor.find_widget(holder) == original
            assert screen._compositor.find_widget(app.query_one("#content")) == before
            assert screen._compositor._dirty_regions
            assert screen._layout_required
            assert not scene_done.is_set()

            # Stop the immediate subscriber before letting the queued next
            # admission run. A held sender must not block its unrelated sibling.
            screen.screen_layout_refresh_signal.unsubscribe(app)
            await asyncio.wait_for(sidebar_done.wait(), 2)
            assert not scene_done.is_set()
        holder.refresh(layout=True)
        await asyncio.wait_for(scene_done.wait(), 2)
        assert not screen._compositor._dirty_regions


async def test_direct_layout_still_publishes_and_unchanged_timer_still_prepares():
    app = FrameApp()
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.preparations.clear()
        app.updates.clear()
        screen._compositor._dirty_regions.add(app.size.region)
        screen._refresh_layout()
        assert screen.preparations == [()]
        assert len(app.updates) == 1

        screen.preparations.clear()
        app.updates.clear()
        screen._scroll_required = True
        screen._on_timer_update()
        assert screen.preparations == [()]
        assert not app.updates
