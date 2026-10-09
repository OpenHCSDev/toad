"""Whole-arrangement reuse must preserve the native placement oracle."""

from fractions import Fraction

import pytest

from textual.app import App
from textual.containers import ScrollableContainer, VerticalGroup
from textual.color import Color
from textual.css.scalar import Scalar, Unit
from textual.geometry import Offset, Size
from textual._measurement import INDEPENDENT_HEIGHT, height_dependency
from textual.layouts.vertical import VerticalLayout
from textual.widgets import Static


async def test_scroll_preserves_measurements_and_source_changes_retire_before_idle():
    app = App()
    async with app.run_test(size=(60, 20)) as pilot:
        child = Static("content")
        child.styles.height = 20
        parent = ScrollableContainer(child)
        parent.styles.width, parent.styles.height = 40, 4
        await app.mount(parent)
        await pilot.pause()
        assert parent.max_scroll_y > 2

        size = parent.container_size
        first = parent.arrange(size)
        box = parent._get_box_model(size, app.size, Fraction(40), Fraction(4))
        dependency = parent.__dict__["_height_arrangement_cache"]
        source_epoch, scene_epoch = parent._layout_updates, parent._geometry_revision
        parent.scroll_to(y=2, animate=False, immediate=True)
        assert parent.scroll_y == 2
        assert parent._geometry_revision > scene_epoch
        assert parent._layout_updates == source_epoch
        assert parent.arrange(size) is first
        assert parent.__dict__["_height_arrangement_cache"] is dependency
        assert parent._get_box_model(size, app.size, Fraction(40), Fraction(4)) is box
        await pilot.pause()
        assert parent.arrange(size) is first

        # Authored source mutation must be visible before its Layout message.
        child.styles.base.set_rule("height", Scalar.parse("21"))
        assert parent._layout_updates > source_epoch
        assert parent.arrange(size) is not first
        before = parent.arrange(size)
        source_epoch, scene_epoch = parent._layout_updates, parent._geometry_revision
        child.update("new content")
        assert parent._layout_updates > source_epoch
        assert parent._geometry_revision > scene_epoch
        assert parent.arrange(size) is not before
        await pilot.pause()

        # Retained-body participation uses the same source owner without
        # scheduling a separate repaint or waiting for native idle delivery.
        before = parent.arrange(size)
        source_epoch, scene_epoch = parent._layout_updates, app.screen._geometry_revision
        flags = parent._layout_required, parent._repaint_required
        parent._invalidate_layout()
        assert parent._layout_updates > source_epoch
        assert app.screen._geometry_revision > scene_epoch
        assert (parent._layout_required, parent._repaint_required) == flags
        assert parent.arrange(size) is not before


async def test_unrelated_style_and_topology_changes_preserve_subtree_reuse():
    app = App()
    async with app.run_test() as pilot:
        parent = VerticalGroup(Static("one"))
        sibling = VerticalGroup(Static("unrelated"))
        await app.mount(parent, sibling)
        await pilot.pause()
        first = parent.arrange(Size(40, 0))
        box = parent._get_box_model(Size(40, 0), app.size, Fraction(40), Fraction(0))
        sibling.styles.color = "red"
        receipt = sibling.mount(Static("another unrelated child"))
        assert parent.arrange(Size(40, 100)) is first
        assert parent._get_box_model(Size(40, 100), app.size, Fraction(40), Fraction(100)) is box
        await receipt


async def test_raw_descendant_style_write_invalidates_without_refresh():
    app = App()
    async with app.run_test() as pilot:
        child = Static("one")
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        first = parent.arrange(Size(40, 0))
        child.styles.base.set_rule("height", Scalar.parse("1fr"))
        current = parent.arrange(Size(40, 100))
        assert current is not first
        assert current.placements[0][1].region.height == 100


async def test_box_reuse_observes_immediate_parent_width_exception():
    app = App()
    async with app.run_test() as pilot:
        leaf = Static("intrinsic width")
        leaf.styles.width = "auto"
        leaf.styles.max_width = "50%"
        leaf.styles.height = 1
        parent = VerticalGroup(leaf)
        parent.styles.width = "auto"
        await app.mount(parent)
        await pilot.pause()
        before = leaf._get_box_model(Size(0, 10), app.size, Fraction(0), Fraction(10))
        assert before.width > 0
        parent.styles.width = 40
        after = leaf._get_box_model(Size(0, 100), app.size, Fraction(0), Fraction(100))
        assert after.width == 0
        assert after is not before


@pytest.mark.parametrize("field,value", [
    ("min_width", "20h"), ("max_width", "50h"),
    ("min_height", "10%"), ("max_height", "50%"),
])
async def test_grid_auto_track_extrema_keep_outer_height_dependency(field, value):
    app = App()
    async with app.run_test() as pilot:
        child = Static("wrapped text " * 10)
        parent = VerticalGroup(child)
        parent.styles.layout = "grid"
        parent.styles.grid_columns = "auto"
        setattr(child.styles, field, value)
        await app.mount(parent)
        await pilot.pause()
        parent._clear_arrangement_cache()
        first = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is not first


@pytest.mark.parametrize("unused_axis", ["width", "height"])
async def test_grid_reuses_only_when_outer_measurement_is_not_called(unused_axis):
    class WidthFromHeight(Static):
        def get_content_width(self, container, viewport):
            return container.height

    class HeightFromHeight(Static):
        def get_content_height(self, container, viewport, width):
            return container.height

    app = App()
    async with app.run_test(size=(80, 24)) as pilot:
        child = (WidthFromHeight if unused_axis == "width" else HeightFromHeight)(
            "wrapping text " * 10
        )
        child.styles.width = "1fr"
        child.styles.height = "auto" if unused_axis == "width" else 2
        parent = VerticalGroup(child)
        parent.styles.layout = "grid"
        parent.styles.height = "auto"
        parent.styles.grid_columns = "1fr"
        parent.styles.grid_rows = "auto" if unused_axis == "width" else "2"
        await app.mount(parent)
        await pilot.pause()

        first = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is first
        # Reuse must agree with a fresh original placement, not just its key.
        parent._clear_arrangement_cache()
        assert parent.arrange(Size(40, 100)).placements == first.placements
        assert parent.arrange(Size(30, 100)) is not first

        # The exact same custom method becomes a real outer-size input as
        # soon as the corresponding auto track actually calls it.
        if unused_axis == "width":
            parent.styles.grid_columns = "auto"
        else:
            parent.styles.grid_rows = "auto"
            child.styles.height = "auto"
        dependent = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is not dependent
        assert parent.arrange(Size(40, 100)).placements != dependent.placements


async def test_local_style_projection_covers_all_raw_mutation_boundaries():
    app = App()
    async with app.run_test() as pilot:
        child = Static("one")
        parent = VerticalGroup(child)
        sibling = VerticalGroup(Static("unrelated"))
        await app.mount(parent, sibling)
        await pilot.pause()
        style = child.styles.base
        for mutate in (
            lambda: style.set_rule("height", Scalar.parse("1fr")),
            lambda: style.clear_rule("height"),
            lambda: style.merge_rules({"height": Scalar.parse("auto")}),
            style.reset,
        ):
            before = parent.arrange(Size(40, 100))
            unrelated = sibling.arrange(Size(40, 100))
            mutate()
            assert parent.arrange(Size(40, 100)) is not before
            assert sibling.arrange(Size(40, 100)) is unrelated


@pytest.mark.parametrize("layout", ["vertical", "horizontal", "stream", "grid"])
async def test_reuse_skips_a_complete_intrinsic_arrangement(layout):
    app = App()
    async with app.run_test() as pilot:
        parent = VerticalGroup(Static("one"), Static("wrapped " * 15))
        parent.styles.layout = layout
        await app.mount(parent)
        await pilot.pause()
        parent._clear_arrangement_cache()
        first = parent.arrange(Size(40, 0))
        assert parent.arrange(Size(40, 200)) is first
        assert parent.arrange(Size(40, 20)) is first
        assert parent.arrange(Size(20, 20)) is not first
        assert parent.arrange(Size(40, 20), optimal=True) is not first


@pytest.mark.parametrize("layout", ["vertical", "horizontal", "stream", "grid"])
async def test_reuse_matches_native_placements_and_invalidates_before_idle(layout):
    app = App()
    async with app.run_test() as pilot:
        inner = VerticalGroup(Static("nested " * 10))
        parent = VerticalGroup(inner, Static("second"))
        parent.styles.layout = layout
        parent.styles.padding = (1, 2)
        inner.styles.margin = (1, 2, 3, 4)
        inner.styles.offset = (1, 2)
        await app.mount(parent)
        await pilot.pause()

        def check():
            sizes = [Size(width, height) for width in (20, 40) for height in (0, 10, 100)]
            # Each original fresh calculation is the reference for reuse;
            # no second class-level authorization controls the same proof.
            expected = []
            for size in sizes:
                parent._clear_arrangement_cache()
                expected.append(parent.arrange(size).placements[:])
            parent._clear_arrangement_cache()
            assert [parent.arrange(size).placements for size in sizes] == expected

        check()
        before = parent.arrange(Size(40, 100))
        inner.children[0].styles.height = 7
        assert parent.arrange(Size(40, 100)) is not before
        check()
        before = parent.arrange(Size(40, 100))
        receipt = inner.mount(Static("admitted before idle"))
        assert parent.arrange(Size(40, 100)) is not before
        await receipt
        check()
        parent.children[1].display = False
        check()
        await pilot.resize_terminal(100, 30)
        check()


@pytest.mark.parametrize("field,value", [
    ("height", "50%"), ("height", "1fr"), ("width", "30h"),
    ("min_height", "10%"), ("max_height", "50%"),
    ("dock", "bottom"), ("split", "bottom"), ("overlay", "screen"),
])
async def test_context_sensitive_flow_keeps_native_height_inputs(field, value):
    app = App()
    async with app.run_test() as pilot:
        child = Static("text")
        parent = VerticalGroup(child)
        await app.mount(parent)
        setattr(child.styles, field, value)
        await pilot.pause()
        parent._clear_arrangement_cache()
        first = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is not first


@pytest.mark.parametrize("layout", ["stream", "grid"])
async def test_direct_content_measurement_cannot_use_a_fixed_box_proof(layout):
    class ContextContent(Static):
        def get_content_height(self, container, viewport, width):
            return container.height + 1

    app = App()
    async with app.run_test() as pilot:
        child = ContextContent("text")
        child.styles.height = 2  # Box is constant; direct content measurement is not.
        parent = VerticalGroup(child)
        parent.styles.layout = layout
        await app.mount(parent)
        await pilot.pause()
        parent._clear_arrangement_cache()
        first = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is not first


@pytest.mark.parametrize("field,value", [
    ("height", "1fr"), ("grid_rows", "1fr"), ("grid_rows", "50%"),
    ("grid_columns", "30h"), ("align_vertical", "middle"),
])
async def test_grid_context_rules_retain_native_arrangements(field, value):
    app = App()
    async with app.run_test() as pilot:
        parent = VerticalGroup(Static("text"))
        parent.styles.layout = "grid"
        setattr(parent.styles, field, value)
        await app.mount(parent)
        await pilot.pause()
        parent._clear_arrangement_cache()
        first = parent.arrange(Size(40, 10))
        assert parent.arrange(Size(40, 100)) is not first


async def test_unknown_layout_hooks_and_scalars_remain_context_sensitive():
    class UnknownLayout(VerticalLayout):
        def arrange(self, parent, children, size, greedy=True):
            return super().arrange(parent, children, size, greedy)

    class UnknownHook(VerticalGroup):
        def pre_layout(self, layout):
            super().pre_layout(layout)

    class UnknownScalar(Scalar):
        def resolve(self, size, viewport, fraction_unit=Fraction(1)):
            return Fraction(size.height)

    app = App()
    async with app.run_test() as pilot:
        layout = VerticalGroup(Static("text"))
        layout.styles.set_rule("layout", UnknownLayout())
        hook = UnknownHook(Static("text"))
        scalar = VerticalGroup(Static("text"))
        scalar.styles.layout = "grid"
        scalar.styles.set_rule("grid_rows", (UnknownScalar(1, Unit.CELLS, Unit.HEIGHT),))
        await app.mount(layout, hook, scalar)
        await pilot.pause()
        for parent in (layout, hook, scalar):
            parent._clear_arrangement_cache()
            first = parent.arrange(Size(40, 10))
            assert parent.arrange(Size(40, 100)) is not first


async def test_paint_rules_preserve_native_content_geometry_across_raw_writes():
    app = App()
    async with app.run_test() as pilot:
        child = Static("unchanged wrapped content " * 6)
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        style = child.styles.inline
        for mutate in (
            lambda: style.set_rule("color", Color.parse("red")),
            lambda: style.clear_rule("color"),
            lambda: style.merge_rules({"color": Color.parse("blue")}),
            lambda: style.replace_rules({"color": Color.parse("green")}),
            style.reset,
        ):
            arrangement = parent.arrange(Size(40, 100))
            model = parent._get_box_model(Size(40, 100), app.size, Fraction(40), Fraction(100))
            paint_revision = parent._subtree_style_revision
            mutate()
            assert parent._subtree_style_revision != paint_revision
            assert parent.arrange(Size(40, 100)) is arrangement
            assert parent._get_box_model(Size(40, 100), app.size, Fraction(40), Fraction(100)) is model


async def test_custom_renderer_keeps_paint_rules_as_measurement_inputs():
    class StyleMeasuredContent(Static):
        def render(self):
            return "one\ntwo\nthree" if self.styles.color == Color.parse("red") else "one"

    app = App()
    async with app.run_test() as pilot:
        child = StyleMeasuredContent()
        child.styles.color = "red"
        parent = VerticalGroup(child)
        await app.mount(parent)
        await pilot.pause()
        size = Size(40, 100)
        fraction = Fraction(40)
        before = child._get_box_model(size, app.size, fraction, fraction)
        assert before.height == 3
        child.styles.inline.set_rule("color", Color.parse("blue"))
        after = child._get_box_model(size, app.size, fraction, fraction)
        assert after.height == 1


async def test_raw_display_rule_publishes_original_native_child_selection():
    app = App()
    async with app.run_test() as pilot:
        first, second = Static("first"), Static("second")
        first.styles.height, second.styles.height = 3, 4
        parent = VerticalGroup(first, second)
        await app.mount(parent)
        await pilot.pause()
        size = Size(40, 100)
        assert parent.get_content_height(size, app.size, size.width) == 7
        second.styles.inline.set_rule("display", "none")
        assert second not in parent.displayed_children
        assert parent.get_content_height(size, app.size, size.width) == 3
        second.styles.inline.clear_rule("display")
        assert second in parent.displayed_children
        assert parent.get_content_height(size, app.size, size.width) == 7


async def test_inherited_paint_mutation_retires_opaque_descendant_measurements():
    class InheritedStyleContent(Static):
        def render(self):
            color = self.rich_style.color.get_truecolor()
            return "one\ntwo\nthree" if color == (255, 0, 0) else "one"

    app = App()
    async with app.run_test() as pilot:
        child = InheritedStyleContent()
        parent = VerticalGroup(child)
        parent.styles.color = "red"
        await app.mount(parent)
        await pilot.pause()
        size = Size(40, 100)
        fraction = Fraction(40)
        assert child._get_box_model(size, app.size, fraction, fraction).height == 3
        # No refresh or idle propagation: the original inherited rule mutation
        # must retire the child's existing render/dimension/box resources too.
        parent.styles.inline.set_rule("color", Color.parse("blue"))
        assert child._get_box_model(size, app.size, fraction, fraction).height == 1


async def test_height_independent_custom_layout_hook_remains_style_sensitive():
    class StyledPlacement(VerticalGroup):
        @height_dependency(INDEPENDENT_HEIGHT)
        def process_layout(self, placements):
            offset = Offset(0, 2 if self.styles.color == Color.parse("red") else 0)
            return [placement._replace(region=placement.region.translate(offset))
                    for placement in placements]

    app = App()
    async with app.run_test() as pilot:
        parent = StyledPlacement(Static("one"))
        parent.styles.color = "red"
        await app.mount(parent)
        await pilot.pause()
        size = Size(40, 100)
        assert parent.arrange(size).placements[0][1].region.y == 2
        parent.styles.inline.set_rule("color", Color.parse("blue"))
        assert parent.arrange(size).placements[0][1].region.y == 0
