"""Reuse only declared height-independent boxes; all other contexts keep native results."""

from fractions import Fraction
from unittest.mock import patch

import pytest

from textual.app import App
from textual.containers import HorizontalGroup, VerticalGroup
from textual.css.scalar import Scalar, Unit
from textual.geometry import Size
from textual.layouts.vertical import VerticalLayout
from textual.layouts.stream import StreamLayout
from textual.widget import Widget
from textual.widgets import Static


async def test_declared_container_selection_publishes_original_measurement_lifetime():
    from textual._measurement import INDEPENDENT_HEIGHT, NATIVE_WIDGET_HEIGHT, height_dependency
    from textual.reactive import reactive

    class SelectedContent(Static):
        show_children = reactive(True, layout=True)

        @property
        @height_dependency(INDEPENDENT_HEIGHT)
        def is_container(self):
            return self.show_children and super().is_container

    class UndeclaredSelection(SelectedContent):
        @property
        def is_container(self):
            return super().is_container

    async with App().run_test() as pilot:
        selected = SelectedContent("leaf")
        selected.styles.width = 20
        selected.styles.height = "auto"
        child = Static("child")
        child.styles.height = 7
        await pilot.app.mount(selected)
        await selected.mount(child)
        await pilot.pause()
        assert selected._native_box_measurement
        first = box(selected, 10)
        assert first.height == 7
        assert box(selected, 30) is first
        selected.show_children = False
        leaf = box(selected, 10)
        assert leaf.height == 1
        assert leaf is not first
        assert box(selected, 30) is leaf
        selected.show_children = True
        child.styles.height = "1fr"
        await pilot.pause()
        assert selected._box_depends_on_available_height()
        assert selected._has_relative_children_height
        selected.show_children = False
        await pilot.pause()
        assert not selected._has_relative_children_height
        assert not selected._box_depends_on_available_height()

        unknown = UndeclaredSelection("unknown")
        assert unknown._native_box_measurement
        assert unknown._box_depends_on_available_height()
        assert NATIVE_WIDGET_HEIGHT.depends(unknown)
        assert NATIVE_WIDGET_HEIGHT.styles_sensitive(selected)


async def test_fractional_placement_and_optimal_measurement_keep_distinct_dependencies():
    class HeightReadingWidth(Widget):
        def get_content_width(self, container, viewport):
            return container.height

    async with App().run_test() as pilot:
        child = HeightReadingWidth()
        child.styles.width = "1fr"
        child.styles.height = 3
        column = VerticalGroup(child)
        await pilot.app.mount(column)
        await pilot.pause()
        assert not child._box_depends_on_available_height(greedy=True)
        assert child._box_depends_on_available_height(greedy=False)
        assert not column._arrangement_depends_on_available_height(optimal=False)
        assert column._arrangement_depends_on_available_height(optimal=True)

        normal = column.arrange(Size(30, 10))
        assert column.arrange(Size(30, 20)) is normal
        optimal = column.arrange(Size(30, 10), optimal=True)
        taller = column.arrange(Size(30, 20), optimal=True)
        assert optimal.placements[0][1].region.width == 10
        assert taller.placements[0][1].region.width == 20
        assert taller is not optimal
        assert column.arrange(Size(30, 20)) is normal
        wider = column.arrange(Size(50, 20))
        assert wider is not normal
        assert wider.placements[0][1].region.width == 50

        # The same original source publication retires both mode answers.
        child.styles.width = "auto"
        assert column._arrangement_depends_on_available_height()
        changed = column.arrange(Size(30, 20))
        assert changed is not normal
        assert changed.placements[0][1].region.width == 20
        await child.remove()
        empty = column.arrange(Size(30, 20))
        assert not empty.placements
        assert not column._arrangement_depends_on_available_height(optimal=True)


async def test_fixed_box_reuses_original_measurement_across_parent_widths():
    async with App().run_test():
        widget = Widget()
        widget.styles.width = 12
        widget.styles.height = 3
        widget.styles.padding = (1, 2)
        widget.styles.margin = (2, 1)
        widget.styles.min_width = 8
        widget.styles.max_width = 20
        first = widget._get_box_model(Size(30, 10), Size(120, 40), Fraction(30), Fraction(10))
        second = widget._get_box_model(Size(70, 10), Size(120, 40), Fraction(70), Fraction(10))
        assert first is second
        assert len(widget._box_model_cache) == 1
        widget.styles.width = 14
        changed = widget._get_box_model(Size(70, 10), Size(120, 40), Fraction(70), Fraction(10))
        assert changed.width != first.width


@pytest.mark.parametrize("width,height", [(None, 3), ("50%", 3), ("1fr", 3), (12, "50w")])
async def test_available_width_inputs_keep_distinct_box_measurements(width, height):
    async with App().run_test():
        widget = Widget()
        widget.styles.width = width
        widget.styles.height = height
        first = widget._get_box_model(Size(30, 20), Size(120, 40), Fraction(30), Fraction(20))
        second = widget._get_box_model(Size(70, 20), Size(120, 40), Fraction(70), Fraction(20))
        assert first != second


async def test_fixed_box_constrain_width_and_viewport_remain_inputs():
    async with App().run_test():
        widget = Widget()
        widget.styles.width = 50
        widget.styles.height = 3
        narrow = widget._get_box_model(Size(20, 10), Size(120, 40), Fraction(20), Fraction(10), constrain_width=True)
        wide = widget._get_box_model(Size(70, 10), Size(120, 40), Fraction(70), Fraction(10), constrain_width=True)
        assert narrow.width == 20
        assert wide.width == 50
        widget.styles.width = "10vw"
        first = widget._get_box_model(Size(30, 10), Size(100, 40), Fraction(30), Fraction(10))
        second = widget._get_box_model(Size(70, 10), Size(200, 40), Fraction(70), Fraction(10))
        assert first.width == 10
        assert second.width == 20


async def test_noncell_width_limit_keeps_original_zero_width_parent_exception():
    async with App().run_test() as pilot:
        child = Widget()
        child.styles.width = 30
        child.styles.height = 3
        child.styles.max_width = "10vw"
        parent = VerticalGroup(child)
        parent.styles.width = "auto"
        await pilot.app.mount(parent)
        first = child._get_box_model(Size(0, 10), Size(120, 40), Fraction(0), Fraction(10))
        second = child._get_box_model(Size(70, 10), Size(120, 40), Fraction(70), Fraction(10))
        assert first.width == 30
        assert second.width == 12


async def test_custom_extrema_keeps_available_parent_width():
    from textual._extrema import Extrema

    class WidthSizedExtrema(Widget):
        def _resolve_extrema(self, container, viewport, width_fraction, height_fraction):
            return Extrema(min_width=Fraction(container.width))

    async with App().run_test():
        widget = WidthSizedExtrema()
        widget.styles.width = 12
        widget.styles.height = 3
        first = widget._get_box_model(Size(30, 10), Size(120, 40), Fraction(30), Fraction(10))
        second = widget._get_box_model(Size(70, 10), Size(120, 40), Fraction(70), Fraction(10))
        assert first.width == 30
        assert second.width == 70


async def test_auto_width_relative_child_keeps_parent_width_expansion():
    async with App().run_test() as pilot:
        child = Widget()
        # Fraction is retained as a relative unit by the inline declaration.
        # Inline percentages are normalized to WIDTH by ScalarProperty.
        child.styles.width = "1fr"
        child.styles.height = 1
        parent = VerticalGroup(child)
        parent.styles.width = "auto"
        parent.styles.height = 3
        await pilot.app.mount(parent)
        await child._mounted_event.wait()
        assert child in parent.children
        assert parent._has_relative_children_width
        first = parent._get_box_model(
            Size(30, 10), Size(120, 40), Fraction(30), Fraction(10)
        )
        second = parent._get_box_model(
            Size(50, 10), Size(120, 40), Fraction(50), Fraction(10)
        )
        assert first.width == 30
        assert second.width == 50
        assert first is not second


async def test_custom_auto_height_keeps_independent_parent_width_input():
    class WidthMeasuredHeight(Widget):
        def get_content_height(self, container, viewport, width):
            return container.width * 2

    async with App().run_test():
        widget = WidthMeasuredHeight()
        widget.styles.width = 12
        widget.styles.height = "auto"
        first = widget._get_box_model(
            Size(30, 10), Size(120, 40), Fraction(30), Fraction(10)
        )
        second = widget._get_box_model(
            Size(50, 10), Size(120, 40), Fraction(50), Fraction(10)
        )
        assert first.height == 60
        assert second.height == 100
        assert first is not second


def box(widget, height, *, width=40, greedy=True):
    return widget._get_box_model(Size(width, height), widget.app.size,
                                 Fraction(width), Fraction(height), greedy=greedy)


async def test_native_nested_flow_reuses_only_unused_height_inputs():
    app = App()
    async with app.run_test() as pilot:
        column = VerticalGroup(HorizontalGroup(Static("first"), Static("second")))
        await app.mount(column)
        await pilot.pause()
        assert not column._box_depends_on_available_height()
        column._box_model_cache.clear()
        with patch.object(column, "get_content_height", wraps=column.get_content_height) as measured:
            first = box(column, 0)
            assert box(column, 300) is first
            assert box(column, 30) is first
            assert measured.call_count == 1
            assert box(column, 300, width=20).width == 20
            assert measured.call_count == 2


@pytest.mark.parametrize("field,value", [
    ("height", "50%"), ("height", "1fr"),
    ("width", "50h"), ("min_width", "20h"), ("max_width", "30h"),
    ("min_height", "40%"), ("min_height", "1fr"), ("max_height", "50%"),
    ("max_height", "50vh"),
])
async def test_height_dependent_css_and_extrema_match_native_contexts(field, value):
    app = App()
    async with app.run_test() as pilot:
        column = VerticalGroup(Static("wrapped text " * 25))
        await app.mount(column)
        setattr(column.styles, field, value)
        await pilot.pause()
        assert column._box_depends_on_available_height()
        expected = {}
        for height in (0, 10, 30, 70):
            column._box_model_cache.clear()
            expected[height] = box(column, height)
        column._box_model_cache.clear()
        for height, measured in expected.items():
            assert box(column, height) == measured


async def test_descendant_style_change_invalidates_proof_before_idle():
    app = App()
    async with app.run_test() as pilot:
        leaf = Static("one")
        column = VerticalGroup(VerticalGroup(leaf))
        await app.mount(column)
        await pilot.pause()
        assert not column._box_depends_on_available_height()
        first = box(column, 0)
        assert box(column, 30) is first
        leaf.styles.height = "1fr"
        assert column._box_depends_on_available_height()
        assert box(column, 100).height != first.height
        leaf.styles.height = 2
        assert not column._box_depends_on_available_height()
        await pilot.pause()
        assert box(column, 30).height == 2


async def test_structural_admission_retires_normalized_boxes():
    app = App()
    async with app.run_test() as pilot:
        inner = VerticalGroup(Static("first"))
        column = VerticalGroup(inner)
        await app.mount(column)
        await pilot.pause()
        before = box(column, 30)
        added = Static("second")
        added.styles.height = 4
        receipt = inner.mount(added)
        assert box(column, 200).height == before.height + 4
        await receipt


async def test_custom_measurement_and_layout_overrides_are_context_dependent():
    class CustomHeight(VerticalGroup):
        def get_content_height(self, container, viewport, width):
            return container.height + 3

    class CustomLayout(VerticalLayout):
        def arrange(self, parent, children, size, greedy=True):
            return super().arrange(parent, children, size, greedy)

    class CustomHook(VerticalGroup):
        def pre_layout(self, layout):
            super().pre_layout(layout)

    class CustomPlacement(VerticalGroup):
        def process_layout(self, placements):
            return placements

    app = App()
    async with app.run_test() as pilot:
        custom = CustomHeight()
        layout = VerticalGroup(Static("auto height"))
        layout.styles.set_rule("layout", CustomLayout())
        hook = CustomHook(Static("auto height"))
        placement = CustomPlacement(Static("auto height"))
        await app.mount(custom, layout, hook, placement)
        await pilot.pause()
        assert box(custom, 10).height == 13
        assert box(custom, 30).height == 33
        observed = {type(widget).__name__: widget._box_depends_on_available_height()
                    for widget in (custom, layout, hook, placement)}
        assert all(observed.values()), observed


@pytest.mark.parametrize("field,value", [("dock", "bottom"), ("split", "bottom"), ("overlay", "screen")])
async def test_flow_rejects_context_sensitive_child_placement(field, value):
    app = App()
    async with app.run_test() as pilot:
        child = VerticalGroup(Static("text"))
        column = VerticalGroup(child)
        await app.mount(column)
        await pilot.pause()
        assert not column._box_depends_on_available_height()
        setattr(child.styles, field, value)
        assert column._box_depends_on_available_height()


async def test_width_and_viewport_scalars_preserve_native_results():
    app = App()
    async with app.run_test() as pilot:
        column = VerticalGroup(Static("text"))
        await app.mount(column)
        await pilot.pause()
        for unit in (Unit.CELLS, Unit.WIDTH, Unit.VIEW_HEIGHT, Unit.VIEW_WIDTH):
            column.styles.height = Scalar(10, unit, Unit.HEIGHT)
            assert not column._box_depends_on_available_height()
            column._box_model_cache.clear()
            expected = box(column, 70)
            assert box(column, 0) == expected
            assert box(column, 70) == expected


async def test_unknown_width_and_stream_overrides_do_not_inherit_a_proof():
    class HeightSizedWidth(Static):
        def get_content_width(self, container, viewport):
            return container.height

    class UnknownStream(StreamLayout):
        def arrange(self, parent, children, size, greedy=True):
            return super().arrange(parent, children, size, greedy)

    app = App()
    async with app.run_test() as pilot:
        width = HeightSizedWidth("text")
        width.styles.width = "auto"
        width.styles.height = 1
        stream = VerticalGroup(Static("text"))
        stream.styles.set_rule("layout", UnknownStream())
        await app.mount(width, stream)
        await pilot.pause()
        assert width._box_depends_on_available_height()
        assert stream._box_depends_on_available_height()
        assert box(width, 10).width == 10
        assert box(width, 30).width == 30


@pytest.mark.parametrize("layout_name", ["vertical", "horizontal", "stream"])
async def test_width_padding_margin_offset_and_viewport_parity(layout_name):
    app = App()
    async with app.run_test() as pilot:
        children = [Static("line one\nline two"), Static("wrapped " * 15)]
        column = VerticalGroup(*children)
        column.styles.layout = layout_name
        column.styles.padding = (1, 2)
        children[0].styles.margin = (1, 2, 3, 4)
        children[1].styles.offset = (1, 2)
        await app.mount(column)
        await pilot.pause()
        inputs = [(width, height, greedy) for width in (20, 40)
                  for height in (0, 10, 100) for greedy in (False, True)]
        expected = []
        for width, height, greedy in inputs:
            column._box_model_cache.clear()
            expected.append(box(column, height, width=width, greedy=greedy))
        column._box_model_cache.clear()
        assert [box(column, height, width=width, greedy=greedy) for width, height, greedy in inputs] == expected


async def test_unset_height_and_custom_extrema_keep_the_full_context():
    from textual._extrema import Extrema

    class CustomExtrema(VerticalGroup):
        def _resolve_extrema(self, container, viewport, width_fraction, height_fraction):
            return Extrema(min_height=Fraction(container.height))

    app = App()
    async with app.run_test() as pilot:
        fill = VerticalGroup(Static("fill"))
        custom = CustomExtrema(Static("extent"))
        await app.mount(fill, custom)
        await pilot.pause()
        fill.styles.base.clear_rule("height")
        fill.styles.inline.clear_rule("height")
        assert fill.styles.height is None
        assert fill._box_depends_on_available_height()
        assert custom._box_depends_on_available_height()
        for height in (10, 30):
            assert box(fill, height).height == height
            assert box(custom, height).height == height


async def test_custom_scalar_resolver_is_not_classified_by_its_unit_alone():
    class ContextScalar(Scalar):
        def resolve(self, size, viewport, fraction_unit=Fraction(1)):
            return Fraction(size.height)

    app = App()
    async with app.run_test() as pilot:
        column = VerticalGroup(Static("text"))
        await app.mount(column)
        await pilot.pause()
        column.styles.height = ContextScalar(1, Unit.CELLS, Unit.HEIGHT)
        assert column._box_depends_on_available_height()
        assert box(column, 10).height == 10
        assert box(column, 30).height == 30


async def test_raw_width_percentage_height_keeps_native_parent_stretch():
    # Native relative-child detection treats every percentage height as
    # relative, even when a raw scalar declares WIDTH as its percentage axis.
    # Preserve that parent stretch behavior rather than only the scalar value.
    app = App()
    async with app.run_test() as pilot:
        child = Static("text")
        column = VerticalGroup(child)
        await app.mount(column)
        await pilot.pause()
        child.styles.set_rule("height", Scalar(50, Unit.PERCENT, Unit.WIDTH))
        child.refresh(layout=True)
        await pilot.pause()
        assert column._has_relative_children_height
        assert column._box_depends_on_available_height()
        assert box(column, 0).height == 20
        assert box(column, 100).height == 100
