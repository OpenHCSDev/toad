from unittest.mock import patch

import pytest

from textual._compositor import Compositor
from textual.app import App
from textual.containers import VerticalGroup
from textual.widgets import Static


class CachedGroup(VerticalGroup):
    CACHE_SUBTREE_GEOMETRY = True


async def test_scrolling_owner_rebuild_borrows_ordinary_child_arrangements():
    """Moving a window preserves unchanged source, exact paint and hit targets."""
    from textual.containers import VerticalScroll

    class MeasuredGroup(VerticalGroup):
        arrangement_calls = 0

        def arrange(self, size, optimal=False):
            self.arrangement_calls += 1
            return super().arrange(size, optimal=optimal)

    class RetainedScroll(VerticalScroll):
        CACHE_SUBTREE_GEOMETRY = True

    rows = [MeasuredGroup(Static(f"ROW {index:02}"), Static("wrapped text " * 9))
            for index in range(30)]
    history = RetainedScroll(*rows, id="history")

    class WindowApp(App):
        CSS = """
        #chrome { dock: top; height: 1; }
        #history { height: 10; }
        Static { height: auto; }
        """

        def compose(self):
            yield Static("UNCHANGED CHROME", id="chrome")
            yield history

    app = WindowApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        # Full acquisition also certifies the original offscreen reader path.
        compositor.reflow(app.screen, app.size)
        original = compositor._subtree_geometry[history]
        first_source = original.child_source(rows[0])
        assert first_source is not None
        assert all(not row.CACHE_SUBTREE_GEOMETRY for row in rows)
        assert all(row not in compositor._subtree_geometry for row in rows)

        def required_scene(scene, targets):
            required = {node for target in targets
                        for node in target.walk_ancestors(with_self=True)}
            return {node: geometry for node, geometry in scene._published_map.items()
                    if geometry.visible_region or node in required}

        def compare_original_scene(targets=()):
            reference = Compositor(max_subtree_geometry_entries=0)
            reference.reflow_visible(app.screen, app.size, retain_geometry=targets)
            assert required_scene(compositor, targets) == required_scene(reference, targets)
            assert compositor.render_strips() == reference.render_strips()
            for y in range(app.size.height):
                for x in range(app.size.width):
                    assert compositor.get_widget_at(x, y) == reference.get_widget_at(x, y)

        for position in (1, 2, 1, 0):
            calls = rows[0].arrangement_calls
            history.scroll_to(y=position, animate=False, immediate=True)
            await pilot.pause()
            assert rows[0].arrangement_calls == calls
            current = compositor._subtree_geometry[history]
            assert current.child_source(rows[0]) is first_source
            compare_original_scene()

        # A previously unexposed target must not receive an invented answer.
        target = rows[25].children[1]
        compositor.reflow_visible(app.screen, app.size, retain_geometry=(target,))
        compare_original_scene((target,))

        # Actual source and width changes revoke their original child resource.
        rows[0].children[1].update("CHANGED SOURCE\n" * 4)
        await pilot.pause()
        assert compositor._subtree_geometry[history].child_source(rows[0]) is not first_source
        compare_original_scene()
        await pilot.resize_terminal(25, 12)
        compare_original_scene()


@pytest.mark.parametrize("capacity", [0, 1, 2, 5])
async def test_geometry_budget_bounds_retention_without_changing_the_scene(capacity):
    app = App()
    async with app.run_test() as pilot:
        groups = [CachedGroup(Static(f"item {index}")) for index in range(4)]
        await app.mount(*groups)
        await pilot.pause()
        compositor = Compositor(max_subtree_geometry_entries=capacity)
        for _ in range(3):
            actual = compositor._arrange_root(app.screen, app.size)
            assert len(compositor._subtree_geometry) <= capacity
        reference = Compositor(max_subtree_geometry_entries=0)._arrange_root(app.screen, app.size)
        assert actual == reference
        compositor.max_subtree_geometry_entries = 0
        assert not compositor._subtree_geometry


async def test_unchanged_subtree_reuses_geometry_and_nested_changes_invalidate_it():
    app = App()
    async with app.run_test() as pilot:
        text = Static("one")
        group = CachedGroup(VerticalGroup(text))
        await app.mount(group)
        await pilot.pause()
        compositor = Compositor(max_subtree_geometry_entries=2)
        compositor._arrange_root(app.screen, app.size)
        with patch.object(group, "arrange", wraps=group.arrange) as arrange:
            compositor._arrange_root(app.screen, app.size)
            assert not arrange.called
        text.update("one\ntwo\nthree")
        await pilot.pause()
        with patch.object(group, "arrange", wraps=group.arrange) as arrange:
            actual = compositor._arrange_root(app.screen, app.size)
            assert arrange.called
        reference = Compositor(max_subtree_geometry_entries=0)._arrange_root(app.screen, app.size)
        assert actual == reference
        compositor.discard_widgets({text})
        assert not compositor._subtree_geometry


async def test_changed_parent_borrows_original_children_without_flat_capture():
    from dataclasses import replace
    from textual._compositor import PlacedSubtreeGeometry, SubtreeGeometryPlacement
    from textual.containers import VerticalScroll
    from textual.screen import Screen

    rows = [CachedGroup(Static(f"row {index}"), Static("wrapped " * 7))
            for index in range(20)]
    history = CachedGroup(*rows)

    class SourceScreen(Screen):
        def compose(self):
            yield VerticalScroll(history)

        def _layout_mutation_roots(self):
            return (history,) if history.lock.is_locked else ()

        def _prepare_compositor_refresh(self):
            return self._layout_mutation_roots()

    class SourceApp(App):
        CSS = "VerticalScroll { height: 10; } Static { height: auto; }"

        def get_default_screen(self):
            return SourceScreen()

    app = SourceApp()
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        original = compositor._subtree_geometry[history]
        stable = rows[5]
        stable_source = original.geometry[stable][1]
        assert isinstance(stable_source, SubtreeGeometryPlacement)
        child = stable.children[1]
        assert child not in original.geometry
        assert original.contains(child)
        assert original.captured_parent(child) is stable
        # Capture the same acquired source with one original child loan. The
        # immutable lifetime must be refused at the parent's reuse owner.
        incoming_clip = stable_source.clip.source
        local = {node: (entry if isinstance(entry, SubtreeGeometryPlacement) else entry.geometry)
                 for node, (_, entry) in original.geometry.items()}
        local[stable] = replace(stable_source, source_held=True)
        loan = type(original).capture(
            original.key, local, original.widgets, original.invisible_widgets,
            {history: incoming_clip}, incoming_clip, set(),
        )
        assert loan.geometry[stable][1].source is stable_source.source
        assert loan.geometry[stable][1].source_held
        assert not loan.reusable
        assert not loan.matches(loan.key)
        assert loan.matches(loan.key, source_held=True)
        assert original.reusable
        # A missing complete child source can lend only its known placed
        # snapshot. A containing capture must not promote that scope.
        partial = PlacedSubtreeGeometry.capture(
            stable_source.key._replace(visible_only=True),
            {stable: stable_source.source.geometry[stable][1].geometry},
            frozenset({stable}), frozenset(), {}, stable_source.clip, set(),
        )
        local[stable] = replace(stable_source, source=partial, source_held=True)
        partial_loan = type(original).capture(
            original.key, local, original.widgets, original.invisible_widgets,
            {history: incoming_clip}, incoming_clip, set(),
        )
        assert partial_loan.contains(stable)
        assert not partial_loan.contains(child)
        assert not partial_loan.complete
        assert not partial_loan.matches(partial_loan.key, require_complete=True, source_held=True)

        rows[0].children[0].update("changed\nheight\nthree")
        inserted = CachedGroup(Static("new row"), Static("new second child"))
        await history.mount(inserted, before=rows[1])
        await pilot.pause()
        current = compositor._subtree_geometry[history]
        assert current is not original
        assert current.geometry[stable][1].source is stable_source.source
        assert len(current.geometry) == len(history.children) + 1
        assert child not in current.geometry
        assert current.contains(child)
        scroll = app.query_one(VerticalScroll)
        targets = (child, rows[12].children[0], rows[-1].children[-1])
        expected = {}
        for position in (0, 18, 3, 55):
            scroll.scroll_to(y=position, animate=False, immediate=True)
            await pilot.pause()
            compositor.reflow_visible(app.screen, app.size, retain_geometry=targets)
            reference = Compositor(max_subtree_geometry_entries=0)
            reference.reflow_visible(app.screen, app.size, retain_geometry=targets)
            demanded = {node for target in targets for node in target.walk_ancestors(with_self=True)}
            # Cached complete sources may retain extra empty clipped boxes.
            # Visible paint and every explicitly required reader must agree.
            def required_scene(source):
                return {node: geometry for node, geometry in source._published_map.items()
                        if geometry.visible_region or node in demanded}
            assert required_scene(compositor) == required_scene(reference)
            expected[position] = required_scene(reference)
            # Complete source membership includes offscreen descendants;
            # uncached visible traversal intentionally does not visit them.
            assert compositor.widgets == reference._arrange_root(
                app.screen, app.size, visible_only=False
            )[1]
            assert compositor.find_widget(child) == reference.find_widget(child)
        held_source = compositor._subtree_geometry[history]
        async with history.lock:
            incomplete = CachedGroup(Static("NOT_COMMITTED"))
            await history.mount(incomplete)
            await pilot.pause()
            for position in (3, 18, 55, 0):
                scroll.scroll_to(y=position, animate=False, immediate=True)
                await pilot.pause()
                compositor.reflow_visible(app.screen, app.size, retain_geometry=targets)
                assert compositor._subtree_geometry[history] is held_source
                assert not held_source.contains(incomplete)
                assert incomplete not in compositor._published_map
                assert required_scene(compositor) == expected[position]
        await incomplete.remove()
        await pilot.pause()
        compositor.reflow(app.screen, app.size)
        reference.reflow(app.screen, app.size)
        assert compositor._published_map == reference._published_map
        await stable.remove()
        await pilot.pause()
        assert stable not in compositor._subtree_geometry
        assert not any(source.contains(child) for source in compositor._subtree_geometry.values())
        assert child not in compositor._published_map


@pytest.mark.parametrize("capacity", [-1, True, 1.5, None])
def test_geometry_budget_rejects_invalid_capacities(capacity):
    with pytest.raises(ValueError, match="non-negative integer"):
        Compositor(max_subtree_geometry_entries=capacity)
