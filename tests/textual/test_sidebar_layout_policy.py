"""Textual-facing: native sidebar geometry preserves peer order and conversation clearance."""

from itertools import product

import pytest
from textual.geometry import Size

from toad.preferences import SavedSettings
from toad.sidebar_layout import (
    BottomSidebarEdge, ChannelsSidebarPlacement, LeftSidebarEdge, RightSidebarEdge,
    SidebarEdge, SidebarLayout, ThreadSidebarPlacement, TopSidebarEdge,
)
from toad.terminal_origin import LocalTerminal, SshTerminal, TerminalOrigin


EDGES = SidebarEdge.members_with(SidebarEdge)


def layout_for(settings: SavedSettings | None = None, origin: type[TerminalOrigin] = LocalTerminal):
    return SidebarLayout(SavedSettings() if settings is None else settings, origin.layout)


def test_moving_swapping_and_resizing_keep_both_sidebars_and_clamp_extent():
    layout = layout_for()
    assert layout.ordered() == (ChannelsSidebarPlacement, ThreadSidebarPlacement)
    assert layout.move(ChannelsSidebarPlacement, RightSidebarEdge)
    assert layout.get(ThreadSidebarPlacement).order == 0
    assert layout.get(ChannelsSidebarPlacement).order == 1
    assert layout.swap(ChannelsSidebarPlacement)
    assert layout.get(ChannelsSidebarPlacement).order == 0
    assert layout.get(ThreadSidebarPlacement).order == 1
    assert layout.ordered() == (ThreadSidebarPlacement, ChannelsSidebarPlacement)
    assert layout.move(ThreadSidebarPlacement, LeftSidebarEdge)
    assert layout.ordered() == (ThreadSidebarPlacement, ChannelsSidebarPlacement)
    assert layout.get(ThreadSidebarPlacement).order == 0
    assert layout.resize(ChannelsSidebarPlacement, 70)
    assert layout.get(ChannelsSidebarPlacement).extent_percent == layout.maximum_percent
    assert layout.resize(ChannelsSidebarPlacement, 1)
    assert layout.get(ChannelsSidebarPlacement).extent_percent == layout.minimum_percent
    assert layout.float_mode(ThreadSidebarPlacement) is True
    assert layout.float_mode(ThreadSidebarPlacement) is False
    assert set(layout.ordered()) == {ThreadSidebarPlacement, ChannelsSidebarPlacement}


@pytest.mark.parametrize("side", EDGES)
def test_two_sidebars_on_one_edge_swap_inward_then_cross(side):
    pair = layout_for()
    pair.move(ChannelsSidebarPlacement, side)
    pair.move(ThreadSidebarPlacement, side)
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
    pair = layout_for()
    pair.move(ChannelsSidebarPlacement, side)
    pair.move(ThreadSidebarPlacement, side)
    collapsed = {ChannelsSidebarPlacement: hide_channels, ThreadSidebarPlacement: hide_thread}
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
    pair.swap(ChannelsSidebarPlacement)
    after = pair.resolve(viewport, dict(reversed(tuple(collapsed.items()))))
    assert {key: side.extent(bar.size) for key, bar in after.bars.items()} == {
        key: side.extent(bar.size) for key, bar in before.bars.items()
    }, "Swap must not change extents through order-dependent rounding"


@pytest.mark.parametrize("side, viewport", list(product(EDGES, (Size(51, 27), Size(36, 18)))))
def test_shrinking_preserves_each_axis_minimum_when_both_controls_fit(side, viewport):
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, side)
    layout.move(ThreadSidebarPlacement, side.opposite())
    layout.resize(ChannelsSidebarPlacement, layout.maximum_percent)
    layout.resize(ThreadSidebarPlacement, layout.minimum_percent)
    resolved = layout.resolve(viewport, {key: False for key in layout.placements})
    assert all(side.extent(bar.size) >= side.minimum for bar in resolved.bars.values())


@pytest.mark.parametrize("channels_edge, thread_edge", list(product(EDGES, repeat=2)))
def test_every_edge_combination_stays_inside_native_viewport(channels_edge, thread_edge):
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, channels_edge)
    layout.move(ThreadSidebarPlacement, thread_edge)
    viewport = Size(52, 70)
    resolved = layout.resolve(viewport, {key: False for key in layout.placements})
    bars = tuple(resolved.bars.values())
    assert all(viewport.region.contains_region(bar) for bar in bars)
    assert not bars[0].overlaps(bars[1])
    assert resolved.gutter.width < viewport.width
    assert resolved.gutter.height < viewport.height


def test_an_arrangement_survives_a_restart_and_each_terminal_keeps_its_own():
    settings = SavedSettings()
    phone = layout_for(settings, SshTerminal)
    assert phone.move(ChannelsSidebarPlacement, BottomSidebarEdge)
    assert phone.resize(ChannelsSidebarPlacement, 22)
    desk = layout_for(settings, LocalTerminal)
    assert desk.get(ChannelsSidebarPlacement) == ChannelsSidebarPlacement.initial()
    restarted = SavedSettings(settings.document())
    for origin, layout in ((SshTerminal, phone), (LocalTerminal, desk)):
        assert layout_for(restarted, origin).placements == layout.placements
    assert layout_for(restarted, SshTerminal).get(ChannelsSidebarPlacement).side is BottomSidebarEdge


def test_sshd_sessions_read_the_ssh_arrangement():
    assert TerminalOrigin.of({"SSH_CONNECTION": "10.0.0.2 51234 10.0.0.1 22"}) is SshTerminal
    assert TerminalOrigin.of({}) is LocalTerminal


@pytest.mark.parametrize("edge", (TopSidebarEdge, BottomSidebarEdge))
def test_a_collapsed_top_or_bottom_bar_is_two_rows_with_its_arrow_on_both(edge):
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, edge)
    resolved = layout.resolve(Size(60, 30), {ChannelsSidebarPlacement: True, ThreadSidebarPlacement: True})
    assert resolved.bars[ChannelsSidebarPlacement].height == 2
    for collapsed in (False, True):
        assert edge.toggle_text(collapsed).split("\n") == [edge.toggle_symbol(collapsed)] * 2
