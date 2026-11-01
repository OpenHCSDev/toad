"""Placement preserves both sidebars, peer order, axis bounds and conversation clearance."""

from itertools import product

import pytest
from textual.geometry import Size

from toad.sidebar_layout import LeftSidebarEdge, RightSidebarEdge, SidebarEdge, SidebarLayout


EDGES = SidebarEdge.members_with(SidebarEdge)


def test_moving_swapping_and_resizing_keep_both_sidebars_and_clamp_extent():
    layout = SidebarLayout()
    assert layout.ordered() == ("channels-sidebar", "thread-sidebar")
    assert layout.move("channels-sidebar", RightSidebarEdge)
    assert layout.get("thread-sidebar").order == 0
    assert layout.get("channels-sidebar").order == 1
    assert layout.swap("channels-sidebar")
    assert layout.get("channels-sidebar").order == 0
    assert layout.get("thread-sidebar").order == 1
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.move("thread-sidebar", LeftSidebarEdge)
    assert layout.ordered() == ("thread-sidebar", "channels-sidebar")
    assert layout.get("thread-sidebar").order == 0
    assert layout.resize("channels-sidebar", 70)
    assert layout.get("channels-sidebar").extent_percent == layout.maximum_percent
    assert layout.resize("channels-sidebar", 1)
    assert layout.get("channels-sidebar").extent_percent == layout.minimum_percent
    assert layout.float_mode("thread-sidebar") is True
    assert layout.float_mode("thread-sidebar") is False
    assert set(layout.ordered()) == {"thread-sidebar", "channels-sidebar"}


@pytest.mark.parametrize("side", EDGES)
def test_two_sidebars_on_one_edge_swap_inward_then_cross(side):
    pair = SidebarLayout()
    pair.move("channels-sidebar", side)
    pair.move("thread-sidebar", side)
    outer, inner = sorted(pair.placements, key=lambda key: pair.get(key).order)
    inward = side.opposite()
    before = dict(pair.placements)
    assert not pair.shift(outer, side) and pair.placements == before
    assert pair.shift(outer, inward)
    assert pair.get(outer).side is pair.get(inner).side is side
    assert pair.get(outer).order == 1 and pair.get(inner).order == 0
    assert pair.shift(outer, inward) and pair.get(outer).side is inward
    assert not pair.shift(outer, inward)


@pytest.mark.parametrize(
    "side, viewport, hide_channels, hide_thread",
    list(product(EDGES, (Size(76, 40), Size(120, 70)), (False, True), (False, True))),
)
def test_float_keeps_order_and_swap_keeps_extents(side, viewport, hide_channels, hide_thread):
    pair = SidebarLayout()
    pair.move("channels-sidebar", side)
    pair.move("thread-sidebar", side)
    collapsed = {"channels-sidebar": hide_channels, "thread-sidebar": hide_thread}
    before = pair.resolve(viewport, collapsed)
    order = pair.ordered()
    for name in order:
        pair.float_mode(name)
        assert pair.ordered() == order, "Float must not reorder sidebars"
        assert pair.resolve(viewport, collapsed).bars == before.bars
    physical = sorted(before.bars.values(), key=lambda bar: side.coordinate(bar.offset))
    assert side.coordinate(physical[0].offset) + side.extent(physical[0].size) == side.coordinate(physical[1].offset)
    assert side.coordinate(physical[0].offset) >= 0
    assert side.coordinate(physical[1].offset) + side.extent(physical[1].size) <= side.extent(viewport)
    for name, hidden in collapsed.items():
        if hidden:
            assert side.extent(before.bars[name].size) == side.collapsed_extent
    pair.swap("channels-sidebar")
    after = pair.resolve(viewport, dict(reversed(tuple(collapsed.items()))))
    assert {key: side.extent(bar.size) for key, bar in after.bars.items()} == {
        key: side.extent(bar.size) for key, bar in before.bars.items()
    }, "Swap must not change extents through order-dependent rounding"


@pytest.mark.parametrize("side, viewport", list(product(EDGES, (Size(51, 27), Size(36, 18)))))
def test_shrinking_preserves_each_axis_minimum_when_both_controls_fit(side, viewport):
    layout = SidebarLayout()
    layout.move("channels-sidebar", side)
    layout.move("thread-sidebar", side.opposite())
    layout.resize("channels-sidebar", layout.maximum_percent)
    layout.resize("thread-sidebar", layout.minimum_percent)
    resolved = layout.resolve(viewport, {key: False for key in layout.placements})
    assert all(side.extent(bar.size) >= side.minimum for bar in resolved.bars.values())


@pytest.mark.parametrize("channels_edge, thread_edge", list(product(EDGES, repeat=2)))
def test_every_edge_combination_stays_inside_native_viewport(channels_edge, thread_edge):
    layout = SidebarLayout()
    layout.move("channels-sidebar", channels_edge)
    layout.move("thread-sidebar", thread_edge)
    viewport = Size(52, 70)
    resolved = layout.resolve(viewport, {key: False for key in layout.placements})
    bars = tuple(resolved.bars.values())
    assert all(viewport.region.contains_region(bar) for bar in bars)
    assert not bars[0].overlaps(bars[1])
    assert resolved.gutter.width < viewport.width
    assert resolved.gutter.height < viewport.height
