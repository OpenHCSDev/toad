"""Native source epochs and opaque getters have distinct height lifetimes."""

from fractions import Fraction

from textual.app import App
from textual.containers import VerticalGroup
from textual.geometry import Size
from textual.widgets import Static


async def test_native_relative_source_changes_before_idle_and_reparent():
    app = App()
    async with app.run_test() as pilot:
        leaf = Static("relative")
        leaf.styles.height = "1fr"
        inner = VerticalGroup(leaf)
        first, second = VerticalGroup(inner), VerticalGroup()
        await app.mount(first, second)
        await pilot.pause()
        assert first._has_relative_children_height
        assert not second._has_relative_children_height
        resource = first._height_dependency_answers()
        first.refresh(repaint=True)
        assert first._height_dependency_answers() is resource
        assert first._has_relative_children_height

        for visible in (False, True):
            leaf.set_display_constraint("relative-source", visible)
            assert first._has_relative_children_height is visible
        leaf.styles.height = 3
        assert not first._has_relative_children_height
        leaf.styles.height = "1fr"
        assert first._has_relative_children_height
        inner.reparent(second)
        assert not first._has_relative_children_height
        assert second._has_relative_children_height
        await pilot.pause()
        assert second._get_box_model(Size(40, 60), app.size, Fraction(40), Fraction(60)).height == 60
        removal = leaf.remove()
        # Pruning owns immediate display retirement, before native unmount.
        assert not second._has_relative_children_height
        await removal


async def test_opaque_display_and_container_getters_do_not_retire_with_native_epochs():
    class LiveDisplay(Static):
        show = True

        @property
        def display(self):
            return self.show and super().display

    class LiveContainer(VerticalGroup):
        show_container = True

        @property
        def is_container(self):
            return self.show_container and super().is_container

    app = App()
    async with app.run_test() as pilot:
        display = LiveDisplay("live")
        display.styles.height = "1fr"
        leaf = Static("leaf")
        leaf.styles.height = "1fr"
        container = LiveContainer(leaf)
        display_parent, container_parent = VerticalGroup(display), VerticalGroup(container)
        await app.mount(display_parent, container_parent)
        await pilot.pause()
        for enabled in (True, False, True, False):
            display.show = enabled
            container.show_container = enabled
            assert display_parent._has_relative_children_height is enabled
            assert container_parent._has_relative_children_height is enabled
            assert "relative_children" not in display_parent._height_dependency_answers()
            assert "relative_children" not in container_parent._height_dependency_answers()


async def test_opaque_relative_getter_remains_live_even_when_it_calls_native_super():
    class LiveRelative(VerticalGroup):
        relative = False

        @property
        def _has_relative_children_height(self):
            return self.relative or super()._has_relative_children_height

    app = App()
    async with app.run_test() as pilot:
        child = LiveRelative(Static("fixed"))
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        for relative in (False, True, False):
            child.relative = relative
            assert parent._has_relative_children_height is relative
            assert "relative_children" not in parent._height_dependency_answers()


async def test_direct_pump_retirement_publishes_display_before_detachment():
    app = App()
    async with app.run_test() as pilot:
        child = Static("relative")
        child.styles.height = "1fr"
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        assert parent._has_relative_children_height
        assert child in parent.displayed_children
        await child._close_messages(wait=False)
        assert not child.display
        assert not parent._has_relative_children_height
        assert child not in parent.displayed_children
        await pilot.pause()


async def test_custom_child_selection_has_its_own_live_lifetime():
    class LiveChildren(VerticalGroup):
        include_children = True

        @property
        def children(self):
            return super().children if self.include_children else ()

    app = App()
    async with app.run_test() as pilot:
        leaf = Static("relative")
        leaf.styles.height = "1fr"
        child = LiveChildren(leaf)
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        try:
            for include in (True, False, True):
                child.include_children = include
                assert parent._has_relative_children_height is include
                assert "relative_children" not in parent._height_dependency_answers()
        finally:
            child.include_children = True
