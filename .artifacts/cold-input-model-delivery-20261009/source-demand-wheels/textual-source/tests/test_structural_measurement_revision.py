"""Native size and arrangement observe the same structural mutation immediately."""

from fractions import Fraction

from textual.app import App
from textual.containers import VerticalGroup
from textual.geometry import Size
from textual.widgets import Static


async def test_nested_admission_invalidates_intrinsic_box_before_idle_delivery():
    app = App()
    async with app.run_test() as pilot:
        first = Static("First")
        first.styles.height = 3
        inner = VerticalGroup(first)
        outer = VerticalGroup(inner)
        await app.mount(outer)
        await pilot.pause()
        size = Size(40, 20)

        def measure():
            return outer._get_box_model(size, app.size, Fraction(40), Fraction(20)).height

        assert measure() == 3
        previous_layout = outer._layout_updates
        added = Static("Second")
        added.styles.height = 4
        receipt = inner.mount(added)
        # Source publication retires measurements before idle delivers Layout.
        # The already-published native child structure is authoritative.
        assert outer._layout_updates > previous_layout
        assert outer.get_content_height(size, app.size, size.width) == 7
        assert measure() == 7, "Parent box reused geometry from the preceding child structure"
        await receipt
        await pilot.pause()
        assert measure() == 7


async def test_native_display_projection_invalidates_nested_measurement_immediately():
    app = App()
    async with app.run_test() as pilot:
        first, second = Static("First"), Static("Second")
        first.styles.height, second.styles.height = 3, 4
        inner = VerticalGroup(first, second)
        outer = VerticalGroup(inner)
        await app.mount(outer)
        await pilot.pause()
        size = Size(40, 20)

        def measure():
            return outer._get_box_model(size, app.size, Fraction(40), Fraction(20)).height

        assert measure() == 7
        for shown, expected in ((False, 3), (True, 7), (False, 3)):
            second.set_display_constraint("fixture", shown)
            assert outer.get_content_height(size, app.size, size.width) == expected
            assert measure() == expected
        await pilot.pause()
