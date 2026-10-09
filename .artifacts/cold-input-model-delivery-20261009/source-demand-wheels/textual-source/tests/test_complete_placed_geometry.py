from textual._compositor import Compositor, PlacedSubtreeGeometry
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class CapturedScroll(VerticalScroll):
    CACHE_SUBTREE_GEOMETRY = True
    arrangement_calls = 0

    def arrange(self, size, optimal=False):
        self.arrangement_calls += 1
        return super().arrange(size, optimal=optimal)


class CompleteSceneApp(App):
    CSS = "CapturedScroll { height: 8; } Static { height: 2; }"

    def compose(self) -> ComposeResult:
        with CapturedScroll():
            for index in range(25):
                yield Static(f"Original row {index}", id=f"row{index}")


async def test_complete_placed_source_serves_viewport_and_retained_paths():
    app = CompleteSceneApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        history = app.query_one(CapturedScroll)
        target = app.query_one("#row23")
        compositor = app.screen._compositor
        compositor.reflow(app.screen, app.size)
        complete = compositor._subtree_geometry[history]
        assert isinstance(complete, PlacedSubtreeGeometry)
        assert not complete.key.visible_only and target in complete.geometry

        history.arrangement_calls = 0
        compositor.reflow_visible(app.screen, app.size, retain_geometry=(target,))
        assert history.arrangement_calls == 0
        assert compositor._subtree_geometry[history] is complete
        target_geometry = compositor._visible_map[target]
        visible = dict(compositor.visible_widgets)
        reference = Compositor(max_subtree_geometry_entries=0)
        reference.reflow_visible(app.screen, app.size, retain_geometry=(target,))
        assert reference.visible_widgets == visible
        assert reference._visible_map[target] == target_geometry

        # A changed scroll scope still needs fresh placement and clipping.
        history.scroll_to(y=6, animate=False, immediate=True)
        history.arrangement_calls = 0
        compositor.reflow_visible(app.screen, app.size, retain_geometry=())
        assert history.arrangement_calls > 0
        partial = compositor._subtree_geometry[history]
        assert partial.key.visible_only

        # This partial source cannot grant a previously unacquired path.
        history.arrangement_calls = 0
        compositor.reflow_visible(app.screen, app.size, retain_geometry=(target,))
        assert history.arrangement_calls > 0
        reference.reflow_visible(app.screen, app.size, retain_geometry=(target,))
        assert reference.visible_widgets == compositor.visible_widgets
        assert reference._visible_map[target] == compositor._visible_map[target]

        # Neither full acquisition nor a changed child can reuse partial data.
        history.arrangement_calls = 0
        compositor.reflow(app.screen, app.size)
        assert history.arrangement_calls > 0
        app.query_one("#row0", Static).styles.height = 4
        history.arrangement_calls = 0
        compositor.reflow_visible(app.screen, app.size, retain_geometry=())
        assert history.arrangement_calls > 0
