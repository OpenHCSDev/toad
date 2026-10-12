"""The placement model cannot duplicate, discard or over-expand a sidebar."""

from itertools import product

import pytest

from toad.sidebar_layout import SidebarLayout


def test_moving_swapping_and_resizing_keep_both_sidebars_and_clamp_width():
    layout = SidebarLayout()
    assert layout.ordered() == ("channels-sidebar", "thread-sidebar")
    assert layout.move("channels-sidebar", "right")
    assert layout.get("thread-sidebar").order == 0
    assert layout.get("channels-sidebar").order == 1
    assert layout.swap("channels-sidebar")
    assert layout.get("channels-sidebar").order == 0
    assert layout.get("thread-sidebar").order == 1
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.move("thread-sidebar", "left")
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.get("thread-sidebar").order == 0
    assert layout.width("channels-sidebar", 70)
    assert layout.get("channels-sidebar").width_percent == 50
    assert layout.width("channels-sidebar", 1)
    assert layout.get("channels-sidebar").width_percent == 15
    assert layout.float_mode("thread-sidebar") is True
    assert layout.float_mode("thread-sidebar") is False
    assert set(layout.ordered()) == {"thread-sidebar", "channels-sidebar"}


@pytest.mark.parametrize("side", ["left", "right"])
def test_two_sidebars_on_one_side_swap_inward_then_cross(side):
    pair = SidebarLayout()
    pair.move("channels-sidebar", side)
    pair.move("thread-sidebar", side)
    outer, inner = sorted(pair.placements, key=lambda key: pair.get(key).order)
    inward = "right" if side == "left" else "left"
    before = dict(pair.placements)
    assert not pair.shift(outer, side) and pair.placements == before
    assert pair.shift(outer, inward)
    assert pair.get(outer).side == pair.get(inner).side == side
    assert pair.get(outer).order == 1 and pair.get(inner).order == 0
    assert pair.shift(outer, inward) and pair.get(outer).side == inward
    assert not pair.shift(outer, inward)


@pytest.mark.parametrize(
    "side, width, hide_left, hide_right", list(product(("left", "right"), (76, 120), (False, True), (False, True))))
def test_float_keeps_order_and_swap_keeps_widths(side, width, hide_left, hide_right):
    pair = SidebarLayout()
    pair.move("channels-sidebar", side)
    pair.move("thread-sidebar", side)
    collapsed = {"channels-sidebar": hide_left, "thread-sidebar": hide_right}
    before = pair.resolve(width, collapsed)
    order = pair.ordered()
    for name in order:
        pair.float_mode(name)
        assert pair.ordered() == order, "Float must not reorder sidebars"
        assert pair.resolve(width, collapsed).bars == before.bars
    physical = sorted(before.bars.values(), key=lambda bar: bar.x)
    assert physical[0].x + physical[0].width == physical[1].x
    assert physical[0].x >= 0 and physical[1].x + physical[1].width <= width
    for name, hidden in collapsed.items():
        if hidden:
            assert before.bars[name].width == 3
    pair.swap("channels-sidebar")
    after = pair.resolve(width, dict(reversed(tuple(collapsed.items()))))
    assert {key: bar.width for key, bar in after.bars.items()} == {
        key: bar.width for key, bar in before.bars.items()
    }, "Swap must not change widths through order-dependent rounding"
