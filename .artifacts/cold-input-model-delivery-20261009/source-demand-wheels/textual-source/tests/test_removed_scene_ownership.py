import asyncio

from textual.app import App
from textual.await_remove import AwaitRemove
from textual.containers import VerticalGroup
from textual.screen import Screen
from textual.selection import SELECT_ALL
from textual.widgets import Static
import pytest


async def test_pending_removal_retires_each_original_scene_and_cover():
    release = asyncio.Event()

    class SlowUnmount(VerticalGroup):
        async def on_unmount(self):
            await release.wait()

    app = App()
    async with app.run_test() as pilot:
        first, second = Screen(), Screen()
        retiring = []
        scenes = []
        for scene in (first, second):
            await app.push_screen(scene)
            node = SlowUnmount(Static("old source"))
            await scene.mount(node)
            node.loading = True
            await pilot.pause()
            cover = node._render_widget
            assert cover is not node
            assert cover in scene._compositor.visible_widgets
            retiring.append((node, cover))
            scenes.append(scene)
        removal = AwaitRemove.prune(*(node for node, _ in retiring))
        try:
            for scene, (node, cover) in zip(scenes, retiring):
                assert node._pruning and not node._closed
                assert cover not in scene._compositor.full_map
                assert cover not in scene._compositor.visible_widgets
                assert node not in scene._compositor.full_map
                assert not node.display
        finally:
            release.set()
            await removal
        assert all(node._closed for node, _ in retiring)


async def test_pending_removal_revokes_pointer_intent_but_keeps_surviving_selection():
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowText(Static):
        async def on_unmount(self):
            entered.set()
            await release.wait()

    app = App()
    async with app.run_test(size=(50, 12)) as pilot:
        try:
            retiring = SlowText("selected source", id="retiring")
            survivor = Static("surviving source", id="survivor")
            parent = VerticalGroup(retiring, survivor)
            await app.mount(parent)
            await pilot.pause()
            assert await pilot.mouse_down(retiring, offset=(0, 0))
            assert not app.screen.selections
            assert app.screen._select_state.end is None
            assert retiring in app.screen._interaction_widgets()
            assert await pilot.mouse_up(retiring, offset=(4, 0))
            screen = app.screen
            state = screen._select_state
            assert state is not None and state.start.content_widget is retiring
            assert state.start.container is parent and state.is_attached_to_dom
            screen.selections = {**screen.selections, survivor: SELECT_ALL}
            retiring.capture_mouse()
            removal = retiring.remove()
            try:
                assert screen._select_state is None
                assert app.mouse_captured is None
                assert app.mouse_over is not retiring and app.hover_over is not retiring
                assert screen.selections == {survivor: SELECT_ALL}
                await asyncio.wait_for(entered.wait(), 1)
                screen._flush_pending_selection()
                assert screen.selections == {survivor: SELECT_ALL}
            finally:
                release.set()
                await removal
            assert parent.is_attached and not state.is_attached_to_dom
            assert screen.get_selected_text() == "surviving source"
        finally:
            release.set()


@pytest.mark.parametrize("layout", ["vertical", "stream"])
async def test_inactive_scene_releases_removed_geometry_and_arrangements(layout):
    app = App()
    async with app.run_test() as pilot:
        parent = VerticalGroup(Static("retire me"), Static("retain me"))
        parent.styles.layout = layout
        await app.mount(parent)
        await pilot.pause()
        owner = app.screen
        removed = parent.children[0]
        survivor = parent.children[1]
        compositor = owner._compositor
        # Warm every derived projection and several geometry/width entries.
        compositor.full_map
        compositor.visible_widgets
        compositor.layers
        retired_offset = removed.region.offset
        list(compositor.get_widgets_at(*retired_offset))
        parent.arrange(parent.size)
        assert removed in compositor._full_map
        await app.push_screen(Screen())
        await pilot.pause()
        await removed.remove()
        await pilot.pause()
        assert removed._closed
        if layout == "stream":
            assert all(placement.widget is not removed
                       for placement in parent.layout._cached_placements or ())
        assert not any(placement.widget is removed
                       for result in parent._arrangement_cache._cache.values()
                       for _, placement in result.placements)
        assert removed not in compositor._full_map
        assert removed not in (compositor._visible_map or {})
        assert removed not in compositor.widgets
        assert removed not in compositor.visible_widgets
        assert all(widget is not removed for widget, _ in compositor.layers)
        assert all(widget is not removed
                   for widget, _ in compositor.get_widgets_at(*retired_offset))
        await app.pop_screen()
        await pilot.pause()
        assert survivor in compositor.visible_widgets
        assert survivor.region.y == parent.content_region.y


async def test_removed_child_damage_is_painted_without_retaining_the_child():
    app = App()
    async with app.run_test() as pilot:
        await app.mount(Static("old content", id="old"), Static("survivor", id="survivor"))
        await pilot.pause()
        retired = app.query_one("#old")
        await retired.remove()
        await pilot.pause()
        rows = app.screen._compositor.render_strips()
        text = "\n".join(strip.text for strip in rows)
        assert "old content" not in text
        assert "survivor" in text
        assert retired not in app.screen._compositor.full_map


async def test_inactive_presentation_policy_preserves_models_and_rebuilds_native_pixels():
    class ColdScreen(Screen):
        RETAIN_INACTIVE_PRESENTATION = False

        def compose(self):
            yield Static("Preserved model: café 界", id="model")

    app = App()
    async with app.run_test() as pilot:
        app.add_mode("cold", ColdScreen)
        app.add_mode("other", Screen)
        await app.switch_mode("cold")
        await pilot.pause()
        owner = app.screen
        model = owner.query_one("#model", Static)
        expected = owner._compositor.render_strips()
        assert model._layout_cache
        await app.switch_mode("other")
        await pilot.pause()
        assert model.is_mounted and not model._closed
        assert model._layout_cache == {}
        assert owner._compositor.root is None
        await app.switch_mode("cold")
        await pilot.pause()
        assert owner.query_one("#model") is model
        assert owner._compositor.render_strips() == expected


async def test_inactive_paint_policy_preserves_geometry_and_rebuilds_pixels():
    class ColdPaintScreen(Screen):
        RETAIN_INACTIVE_PAINT = False

        def compose(self):
            yield VerticalGroup(Static("Preserved model: café 界", id="model"), id="group")

    app = App()
    async with app.run_test() as pilot:
        app.add_mode("paint", ColdPaintScreen)
        app.add_mode("other", Screen)
        await app.switch_mode("paint")
        await pilot.pause()
        owner = app.screen
        model = owner.query_one("#model", Static)
        parent = owner.query_one("#group", VerticalGroup)
        expected = owner._compositor.render_strips()
        arrangement = parent.arrange(parent.size)
        assert model._layout_cache and model._styles_cache._cache
        await app.switch_mode("other")
        await pilot.pause()
        assert model.is_mounted and not model._closed
        assert not model._layout_cache and not model._styles_cache._cache
        assert owner._compositor.root is owner
        assert parent.arrange(parent.size) is arrangement
        await app.switch_mode("paint")
        await pilot.pause()
        assert owner.query_one("#model") is model
        assert owner._compositor.render_strips() == expected


async def test_visible_backdrop_does_not_retire_its_paint():
    class ColdPaintScreen(Screen):
        RETAIN_INACTIVE_PAINT = False

        def compose(self):
            yield Static("backdrop", id="model")

    class Overlay(Screen):
        DEFAULT_CSS = "Overlay { background: transparent; }"

    app = App()
    async with app.run_test() as pilot:
        await app.push_screen(ColdPaintScreen())
        await pilot.pause()
        owner = app.screen
        model = owner.query_one("#model", Static)
        owner._compositor.render_strips()
        cached_lines = dict(model._styles_cache._cache)
        await app.push_screen(Overlay())
        await pilot.pause()
        assert owner in app._background_screens
        owner._retire_inactive_paint()
        assert model._styles_cache._cache == cached_lines
