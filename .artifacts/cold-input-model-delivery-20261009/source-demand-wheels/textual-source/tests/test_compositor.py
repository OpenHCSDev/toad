from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Static
from unittest.mock import patch
import gc
from types import FunctionType
import pytest


async def test_point_hits_follow_layer_clip_visibility_and_scene_changes():
    from textual.errors import NoWidget
    from textual.geometry import Region

    class PointApp(App):
        CSS = """
        #pane { width: 8; height: 4; offset: 2 2; layers: back front; }
        #back, #front { width: 12; height: 3; }
        #back { layer: back; }
        #front { layer: front; }
        """

        def compose(self):
            yield Container(Static("back", id="back"), Static("front", id="front"), id="pane")

    app = PointApp()
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        pane = app.query_one("#pane")
        back = app.query_one("#back")
        front = app.query_one("#front")
        compositor = app.screen._compositor

        # Paint admission clips pixels without changing the original source
        # origin/extent returned to hit and pager geometry consumers.
        assert compositor.visible_widgets[front] == (
            Region(2, 2, 12, 3), Region(2, 2, 8, 3),
        )
        assert compositor.find_widget(front).clip == Region(2, 2, 8, 4)
        assert compositor.get_widget_at(3, 2) == (front, front.region)
        assert [widget for widget, _ in compositor.get_widgets_at(3, 2)] == [
            front, back, pane, app.screen,
        ]
        # Children extend beyond their container; those cells belong to Screen.
        assert compositor.get_widget_at(10, 2)[0] is app.screen
        assert compositor.get_widget_at(3, 6)[0] is app.screen
        for x, y in [(-1, 2), (20, 2), (3, -1), (3, 10)]:
            assert list(compositor.get_widgets_at(x, y)) == []
            with pytest.raises(NoWidget):
                compositor.get_widget_at(x, y)

        front.visible = False
        await pilot.pause()
        assert front not in compositor.visible_widgets
        assert compositor.get_widget_at(3, 2)[0] is back
        assert all(widget is not front for widget, _ in compositor.get_widgets_at(3, 2))
        front.visible = True
        pane.styles.offset = (4, 3)
        await pilot.pause()
        assert compositor.visible_widgets[front] == (
            Region(4, 3, 12, 3), Region(4, 3, 8, 3),
        )
        assert compositor.get_widget_at(3, 2)[0] is app.screen
        assert compositor.get_widget_at(5, 3)[0] is front

        pane.styles.offset = (-2, -1)
        await pilot.pause()
        assert compositor.visible_widgets[front] == (
            Region(-2, -1, 12, 3), Region(0, 0, 6, 2),
        )
        assert compositor.get_widget_at(0, 0) == (front, Region(-2, -1, 12, 3))
        assert compositor.cuts[0] == [0, 6, 20]
        assert compositor.cuts[2] == [0, 6, 20]
        assert compositor.cuts[3] == [0, 20]

        # A completely clipped descendant still belongs to native geometry,
        # but contributes neither paint pixels nor pointer hits.
        front.styles.offset = (8, 0)
        await pilot.pause()
        assert front in compositor.widgets and front in compositor.full_map
        assert front not in compositor.visible_widgets
        assert compositor.get_widget_at(0, 0)[0] is back
        pane.styles.offset = (4, 3)
        front.styles.offset = (0, 0)
        await pilot.pause()
        await front.remove()
        await pilot.pause()
        assert compositor.get_widget_at(5, 3)[0] is back


async def test_reflow_releases_recursive_closures_without_gc():
    app = App()
    names = {"Compositor._arrange_root.<locals>.add_widget",
             "Compositor._arrange_root.<locals>.arrange_widget"}

    def retained_closures():
        return {id(value) for value in gc.get_objects()
                if type(value) is FunctionType and value.__qualname__ in names}

    async with app.run_test() as pilot:
        await pilot.pause()
        enabled = gc.isenabled()
        gc.disable()
        try:
            before = retained_closures()
            for _ in range(20):
                app.screen._compositor._arrange_root(app.screen, app.screen.size)
            assert retained_closures() == before, "Finished reflows retained their scene graphs"
        finally:
            if enabled:
                gc.enable()


async def test_compositor_scroll_placements():
    """Regression test for https://github.com/Textualize/textual/issues/5249
    The Static should remain visible.
    """

    class ScrollApp(App):
        CSS = """
        Screen {
            overflow: scroll;
        }
        Container {
            width: 200vw;
        }
        #hello {
            width: 20;
            height: 10;
            offset: 50 10;
            background: blue;
            color: white;
        }
        """

        def compose(self) -> ComposeResult:
            with Container():
                yield Static("Hello", id="hello")

        def on_mount(self) -> None:
            self.screen.scroll_to(20, 0, animate=False)

    app = ScrollApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        static = app.query_one("#hello")
        widgets = app.screen._compositor.visible_widgets
        # The static wasn't scrolled out of view, and should be visible
        # This wasn't the case <= v0.86.1
        assert static in widgets


async def test_full_reflow_replaces_invalidated_scroll_map():
    app = App()
    async with app.run_test() as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        compositor.reflow_visible(
            app.screen, app.screen.size, retain_geometry=app.screen._layout_geometry_targets(),
        )
        assert compositor._full_map_invalidated
        compositor.reflow(app.screen, app.screen.size)
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            assert compositor.full_map is compositor._full_map
            arrange.assert_not_called()


async def test_layout_geometry_reads_do_not_recursively_rebuild_scene():
    from textual.geometry import Size

    class GeometryReader(Static):
        def get_content_height(self, container, viewport, width):
            # Layouts/widgets can consult their last committed geometry while
            # measuring. That read must not recursively start the same layout.
            self.parent.region
            return super().get_content_height(container, viewport, width)

    class GeometryApp(App):
        CSS = "Container { height: auto; } GeometryReader { height: auto; }"

        def compose(self):
            with Container():
                yield GeometryReader("Word " * 30)

    app = GeometryApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        # Scrolling invalidates the full map; a later width change needs one
        # full arrangement, not a second one from measurement's geometry read.
        compositor.reflow_visible(
            app.screen, app.screen.size, retain_geometry=app.screen._layout_geometry_targets(),
        )
        assert compositor._full_map_invalidated
        with patch.object(compositor, "_arrange_root", wraps=compositor._arrange_root) as arrange:
            compositor.reflow(app.screen, Size(45, 20))
            assert arrange.call_count == 1
        actual = compositor.full_map.copy()
        # Force a fresh native pass over the same complete tree for comparison.
        compositor.reflow(app.screen, Size(45, 20))
        assert compositor.full_map == actual

        # A failed lazy measurement must retain its invalidation so the next
        # geometry lookup retries, instead of treating the old map as current.
        compositor._full_map_invalidated = True
        with patch.object(app.screen, "arrange", side_effect=ValueError("measure failed")):
            with pytest.raises(ValueError, match="measure failed"):
                compositor.full_map
        assert not compositor._arranging and compositor._full_map_invalidated
        assert compositor.full_map == actual


async def test_layer_inheritance_updates_between_reflows():
    class LayersApp(App):
        CSS = """
        Container { height: 5; }
        Static { width: 10; height: 1; dock: top; }
        #low { layer: low; }
        #high { layer: high; }
        """

        def compose(self):
            with Container(id="outer"):
                with Container(id="inner"):
                    yield Static("LOW", id="low")
                    yield Static("HIGH", id="high")

    app = LayersApp()
    async with app.run_test() as pilot:
        outer = app.query_one("#outer")
        inner = app.query_one("#inner")
        low = app.query_one("#low")
        high = app.query_one("#high")
        outer.styles.layers = ("low", "high")
        inner.styles.layers = ("high", "low")
        await pilot.pause()
        geometry = app.screen._compositor.full_map
        assert geometry[high].order > geometry[low].order
        outer.styles.layers = ("high", "low")
        await pilot.pause()
        geometry = app.screen._compositor.full_map
        assert geometry[low].order > geometry[high].order

        # Capturing a nested root must inherit the same original declaration
        # outside its scope, including explicit empty and duplicate public names.
        for names in ((), ("default",), ("low", "high", "low")):
            outer.styles.layers = names
            assert inner.layers == names
            await pilot.pause()
            compositor = app.screen._compositor
            geometry = compositor.full_map
            captured, _ = compositor._arrange_root(
                inner, app.screen.size, visible_only=False,
                root_geometry=geometry[inner],
            )
            assert captured[low].order == geometry[low].order
            assert captured[high].order == geometry[high].order

        detached = Container()
        assert detached.layers == ("default",)
        detached.styles.layers = ("high", "low", "high")
        assert detached.layers == ("high", "low", "high")


async def test_custom_widget_layers_are_respected():
    class CustomLayers(Container):
        @property
        def layers(self):
            return ("high", "low")

    class LayersApp(App):
        CSS = """
        Container { height: 5; }
        Static { width: 10; height: 1; dock: top; }
        #low { layer: low; }
        #high { layer: high; }
        """

        def compose(self):
            with CustomLayers():
                yield Static("LOW", id="low")
                yield Static("HIGH", id="high")

    app = LayersApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        geometry = app.screen._compositor.full_map
        assert geometry[app.query_one("#low")].order > geometry[app.query_one("#high")].order


async def test_covered_widgets_skip_rendering_without_changing_output():
    class CoverApp(App):
        CSS = """
        Container { width: 100%; height: 100%; background: $primary; }
        Static { width: 100%; height: 100%; background: $background 40%; }
        """

        def compose(self):
            with Container():
                with Container():
                    yield Static("Covered backgrounds\nUnicode café 界", id="foreground")

    app = CoverApp()
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        outer = app.query_one(Container)
        with patch.object(outer, "render_lines", wraps=outer.render_lines) as render:
            optimized = compositor.render_strips()
            render.assert_not_called()
            original = compositor._get_renders
            # Render every layer as before, using the exact same geometry.
            with patch.object(compositor, "_get_renders", lambda crop=None, render_regions=None, *, widgets: original(crop, widgets=widgets)):
                reference = compositor.render_strips()
            assert render.call_count > 0
        assert optimized == reference


@pytest.mark.parametrize("rows", [(2, 3), (1, 8), (0, 2, 3, 7, 8)])
async def test_partial_redraw_requests_only_damaged_vertical_rows(rows):
    from textual.geometry import Region

    class Counted(Static):
        def __init__(self):
            self.requested_rows = []
            super().__init__("\n".join(f"Row {index}: café 界" for index in range(40)))

        def render_lines(self, crop):
            self.requested_rows.extend(crop.line_range)
            return super().render_lines(crop)

    class DamageApp(App):
        CSS = "Container { height: 10; overflow-y: scroll; } Counted { height: 40; }"

        def compose(self):
            with Container():
                yield Counted()

    app = DamageApp()
    async with app.run_test(size=(40, 15)) as pilot:
        container = app.query_one(Container)
        widget = app.query_one(Counted)
        compositor = app.screen._compositor
        for scroll_y in (0, 5):
            container.scroll_to(y=scroll_y, animate=False, immediate=True)
            await pilot.pause()
            damage = {Region(3, y, 7, 1) for y in rows}
            widget.requested_rows.clear()
            compositor._dirty_regions = damage.copy()
            actual = compositor.render_partial_update()
            assert widget.requested_rows == [y + scroll_y for y in rows]

            # Native whole-height rendering must generate identical terminal
            # operations/metadata for the same dirty spans, including x clipping.
            original = compositor._get_renders
            with patch.object(compositor, "_get_renders", lambda crop=None, render_regions=None, *, widgets: original(None, widgets=widgets)):
                compositor._dirty_regions = damage.copy()
                expected = compositor.render_partial_update()
            assert actual.render_segments(app.console) == expected.render_segments(app.console)


async def test_partly_covered_widgets_render_only_exposed_rows():
    class Counted(Static):
        def __init__(self):
            super().__init__("\n".join(f"[bold]Row {y}[/bold]: café 界" for y in range(20)))
            self.requested_rows = []

        def render_lines(self, crop):
            self.requested_rows.extend(crop.line_range)
            return super().render_lines(crop)

    class CoverApp(App):
        CSS = """
        Screen { layers: content overlay; }
        Counted { width: 100%; height: 20; layer: content; }
        #cover { width: 100%; height: 12; offset: 0 4; layer: overlay; dock: top; }
        """

        def compose(self):
            yield Counted()
            yield Static("Foreground", id="cover")

    app = CoverApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        widget = app.query_one(Counted)
        compositor = app.screen._compositor
        widget.requested_rows.clear()
        actual = compositor.render_strips()
        assert widget.requested_rows == [*range(4), *range(16, 20)]
        original = compositor._get_renders
        with patch.object(compositor, "_get_renders", lambda crop=None, render_regions=None, *, widgets: original(crop, widgets=widgets)):
            expected = compositor.render_strips()
        assert actual == expected


async def test_screen_membership_reads_do_not_acquire_geometry():
    """Status is the committed scene; explicit position reads may widen it."""
    import cProfile
    from textual.containers import VerticalScroll

    class MembershipApp(App):
        CSS = "VerticalScroll { height: 3; } Static { height: 1; } #hidden { display: none; }"

        def compose(self):
            yield VerticalScroll(*(Static(str(index), id=f"row-{index}")
                                   for index in range(30)))
            yield Static("hidden", id="hidden")

    app = MembershipApp()
    detached = Static("detached")
    assert not detached.is_on_screen
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        compositor.reflow_visible(app.screen, app.screen.size, retain_geometry=())
        assert compositor._full_map_invalidated
        hidden = app.query_one("#hidden")
        last = app.query_one("#row-29")
        first = app.query_one("#row-0")
        scene = compositor._published_map
        assert first in scene and last not in scene and hidden not in scene
        profile = cProfile.Profile()
        with profile:
            for _ in range(40):
                assert first.is_on_screen
                assert not last.is_on_screen
                assert not hidden.is_on_screen
        assert compositor._published_map is scene
        assert compositor._full_map_invalidated
        assert not any(entry.code.co_name == "_arrange_root"
                       for entry in profile.getstats()
                       if not isinstance(entry.code, str))
        # A genuine geometry demand retains the offscreen path in this scene.
        assert compositor.find_widget(last).virtual_region.y > 0
        assert last.is_on_screen
        assert not hidden.is_on_screen
