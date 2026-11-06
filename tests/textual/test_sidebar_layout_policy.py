"""Textual-facing: native sidebar geometry preserves peer order and conversation clearance."""

from itertools import product

import pytest
from textual.geometry import Size

from toad.preferences import SavedSettings
from toad.sidebar_layout import SidebarLayout
from toad.sidebar_placement import (
    BottomSidebarEdge, ChannelsSidebarPlacement, HeightSidebarEdge, LeftSidebarEdge, RightSidebarEdge,
    SidebarEdge, ThreadSidebarPlacement, TopSidebarEdge,
)
from toad.terminal_origin import LocalTerminal, SshTerminal, TerminalOrigin


EDGES = SidebarEdge.members_with(SidebarEdge)


def side_by_side(first, second) -> bool:
    """Two bars on one edge sit next to each other across the screen, never on top of each
    other: left and right bars touch, top and bottom bars share a band split by a splitter."""
    left, right = sorted((first, second), key=lambda region: region.x)
    return not left.overlaps(right) and 0 <= right.x - left.right <= HeightSidebarEdge.splitter


def layout_for(settings: SavedSettings | None = None, origin: type[TerminalOrigin] = LocalTerminal):
    return SidebarLayout(SavedSettings() if settings is None else settings, origin)


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
def test_two_sidebars_on_one_edge_swap_onward_then_move_there(side):
    """Toward the neighbour (inward for columns, rightward along a band) the first arrow
    swaps, the next moves the bar to that edge, and its own wall then stops it."""
    pair = layout_for()
    pair.move(ChannelsSidebarPlacement, side)
    pair.move(ThreadSidebarPlacement, side)
    first, second = sorted(pair.placements, key=lambda key: pair.get(key).order)
    onward = side.onward()
    before = dict(pair.placements)
    assert not pair.shift(first, side) and pair.placements == before
    assert pair.shift(first, onward)
    assert pair.get(first).side is pair.get(second).side is side
    assert pair.get(first).order == 1 and pair.get(second).order == 0
    assert pair.shift(first, onward) and pair.get(first).side is onward
    assert not pair.shift(first, onward)


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
    first_bar, second_bar = before.bars.values()
    assert not first_bar.overlaps(second_bar), before.bars
    assert all(viewport.region.contains_region(bar) for bar in before.bars.values())
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
def test_a_collapsed_top_or_bottom_bar_is_two_rows_its_heading_between_arrows(edge):
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, edge)
    resolved = layout.resolve(Size(60, 30), {ChannelsSidebarPlacement: True, ThreadSidebarPlacement: True})
    assert resolved.bars[ChannelsSidebarPlacement].height == 2
    for collapsed in (False, True):
        symbol = edge.toggle_symbol(collapsed)
        assert edge.toggle_text(collapsed, "all").split("\n") == [f"{symbol}  all  {symbol}", symbol]


@pytest.mark.parametrize("side, resized, percent", list(product(
    SidebarEdge.members_with(HeightSidebarEdge), (ChannelsSidebarPlacement, ThreadSidebarPlacement),
    (25, SidebarLayout.maximum_percent),
)))
def test_resizing_either_bar_in_a_band_resizes_the_whole_band(side, resized, percent):
    """The band takes one height: the largest band is not shrunk as if its bars stacked."""
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, side)
    layout.move(ThreadSidebarPlacement, side)
    assert len({placement.extent_percent for placement in layout.placements.values()}) == 1
    assert layout.resize(resized, percent)
    bars = layout.resolve(Size(80, 40), {key: False for key in layout.placements}).bars
    assert side_by_side(*bars.values()), bars
    assert {side.extent(bar.size) for bar in bars.values()} == {40 * percent // 100}, bars


@pytest.mark.parametrize("side", SidebarEdge.members_with(HeightSidebarEdge))
def test_a_band_split_shares_the_width_survives_other_changes_and_keeps_both_bars_usable(side):
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, side)
    layout.move(ThreadSidebarPlacement, side)
    open_bars = {key: False for key in layout.placements}

    def widths() -> list[int]:
        bars = layout.resolve(Size(80, 40), open_bars).bars
        assert side_by_side(*bars.values()), bars
        return [bar.width for bar in sorted(bars.values(), key=lambda bar: bar.x)]

    assert widths() == [40, 40]
    assert layout.set_split(side, 70)
    assert widths() == [56, 24]
    layout.resize(ThreadSidebarPlacement, 30)
    layout.swap(ThreadSidebarPlacement)
    assert layout.split(side) == 70 and widths() == [56, 24], "Placement changes keep the split"
    assert layout.set_split(side, 0)
    assert widths() == [HeightSidebarEdge.cross_minimum, 80 - HeightSidebarEdge.cross_minimum]
    first, second = layout.ordered()
    for folds in product((False, True), repeat=2):
        collapsed = dict(zip((first, second), folds))
        splitters = sum(layout.splits_after(bar, collapsed) for bar in (first, second))
        for shown, folded in collapsed.items():
            assert not layout.splits_after(shown, {shown: folded}), "A hidden neighbour draws no splitter"
        assert splitters == (folds[0] is folds[1]), (
            "One splitter separates bars sharing a row, both open or both folded; none otherwise")
    reloaded = layout_for(SavedSettings(layout.settings.document()))
    assert reloaded.split(side) == 0 and reloaded.placements == layout.placements, "The split is saved"


@pytest.mark.parametrize("side", SidebarEdge.members_with(HeightSidebarEdge))
def test_one_open_bar_in_a_band_takes_the_band_and_only_two_open_bars_split_it(side):
    """A folded bar beside an open one is only its toggle: it lies along the wall as a
    full-width strip, and the open bar takes the whole width beside it. Held half the band,
    the open bar got half the room it asked for; held the narrowest bar width, still less."""
    layout = layout_for()
    layout.move(ChannelsSidebarPlacement, side)
    layout.move(ThreadSidebarPlacement, side)
    first, second = layout.ordered()

    def bars(collapsed: dict):
        resolved = layout.resolve(Size(80, 40), collapsed).bars
        return resolved[first], resolved[second]

    assert [bar.width for bar in bars({first: False, second: False})] == [40, 40]
    for opened, folded in ((first, second), (second, first)):
        placed = dict(zip((first, second), bars({opened: False, folded: True})))
        assert placed[opened].width == placed[folded].width == 80
        assert placed[folded].height == HeightSidebarEdge.collapsed_extent
        assert not placed[opened].overlaps(placed[folded]), placed
    assert [bar.width for bar in bars({first: True, second: True})] == [40, 40], "Two folded bars share the band"

def test_the_thread_bar_names_the_viewed_tab_and_the_channels_bar_its_scope():
    """The toggle names what the bar shows: the viewed tab's own title, the one the tab bar
    draws, or the bar's scope while no tab is viewed."""
    assert ThreadSidebarPlacement.heading(["#comms"]) == "#comms"
    assert ThreadSidebarPlacement.heading([]) == ThreadSidebarPlacement.scope
    assert ChannelsSidebarPlacement.heading(["#comms"]) == ChannelsSidebarPlacement.scope
    for edge in EDGES:
        text = edge.toggle_text(False, "#comms")
        assert "#comms" in text.replace("\n", "") and text.count(edge.toggle_symbol(False)) >= 2
