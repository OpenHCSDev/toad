import pytest

from textual._arrange import TOP_Z, arrange
from textual._context import active_app
from textual.app import App
from textual.geometry import NULL_OFFSET, Region, Size, Spacing
from textual.layout import DockArrangeResult, WidgetPlacement
from textual.widget import Widget


def test_placement_admission_keeps_original_rank_and_retained_targets():
    repeated, offscreen, fixed = Widget(), Widget(), Widget()
    first = WidgetPlacement(Region(0, 0, 10, 1), NULL_OFFSET, Spacing(), repeated)
    older = WidgetPlacement(Region(0, 100, 10, 1), NULL_OFFSET, Spacing(), offscreen)
    second = WidgetPlacement(Region(0, 40, 10, 1), NULL_OFFSET, Spacing(), repeated)
    pinned = WidgetPlacement(Region(0, 200, 10, 1), NULL_OFFSET, Spacing(), fixed,
                             order=TOP_Z, fixed=True)
    result = DockArrangeResult.from_placements([first, older, second, first, pinned],
                                              {repeated, offscreen, fixed}, Spacing())
    # Spatial bucket duplication and equal source placements remain deduplicated;
    # a fixed placement still precedes the queried scrolling placements.
    assert result.get_visible_placements(Region(0, 0, 10, 1)) == [(4, pinned), (0, first)]
    original_resource = result.spatial_map
    # Retaining an offscreen target selects original list order, including all
    # placements of the selected widgets. One widget keeps its first rank.
    expected = [(0, first), (1, older), (0, second), (0, first), (4, pinned)]
    assert result.get_visible_placements(Region(0, 0, 10, 1), retain=(offscreen,)) == expected
    assert result.get_visible_placements(Region(0, 0, 10, 300)) == expected
    assert result.get_visible_placements(Region(0, 0, 10, 300)) is result.placements
    assert result.spatial_map is original_resource


async def test_arrange_empty():
    container = Widget(id="container")

    result = arrange(container, [], Size(80, 24), Size(80, 24))
    assert result.placements == []
    assert result.widgets == set()


async def test_arrange_dock_top():
    container = Widget(id="container")
    app = App()
    active_app.set(app)
    container._parent = app
    child = Widget(id="child")
    header = Widget(id="header")
    header.styles.dock = "top"
    header.styles.height = "1"

    result = arrange(container, [child, header], Size(80, 24), Size(80, 24))

    assert [placement for _, placement in result.placements] == [
        WidgetPlacement(
            Region(0, 0, 80, 1), NULL_OFFSET, Spacing(), header, order=TOP_Z, fixed=True
        ),
        WidgetPlacement(
            Region(0, 1, 80, 23), NULL_OFFSET, Spacing(), child, order=0, fixed=False
        ),
    ]
    assert result.widgets == {child, header}


async def test_arrange_dock_left():
    container = Widget(id="container")
    app = App()
    active_app.set(app)
    container._parent = app
    child = Widget(id="child")
    header = Widget(id="header")
    header.styles.dock = "left"
    header.styles.width = "10"

    result = arrange(container, [child, header], Size(80, 24), Size(80, 24))
    assert [placement for _, placement in result.placements] == [
        WidgetPlacement(
            Region(0, 0, 10, 24),
            NULL_OFFSET,
            Spacing(),
            header,
            order=TOP_Z,
            fixed=True,
        ),
        WidgetPlacement(
            Region(10, 0, 70, 24), NULL_OFFSET, Spacing(), child, order=0, fixed=False
        ),
    ]
    assert result.widgets == {child, header}


async def test_arrange_dock_right():
    container = Widget(id="container")
    app = App()
    active_app.set(app)
    container._parent = app
    child = Widget(id="child")
    header = Widget(id="header")
    header.styles.dock = "right"
    header.styles.width = "10"

    result = arrange(container, [child, header], Size(80, 24), Size(80, 24))
    assert [placement for _, placement in result.placements] == [
        WidgetPlacement(
            Region(70, 0, 10, 24),
            NULL_OFFSET,
            Spacing(),
            header,
            order=TOP_Z,
            fixed=True,
        ),
        WidgetPlacement(
            Region(0, 0, 70, 24), NULL_OFFSET, Spacing(), child, order=0, fixed=False
        ),
    ]
    assert result.widgets == {child, header}


async def test_arrange_dock_bottom():
    container = Widget(id="container")
    app = App()
    active_app.set(app)
    container._parent = app
    child = Widget(id="child")
    header = Widget(id="header")
    header.styles.dock = "bottom"
    header.styles.height = "1"

    result = arrange(container, [child, header], Size(80, 24), Size(80, 24))
    assert [placement for _, placement in result.placements] == [
        WidgetPlacement(
            Region(0, 23, 80, 1),
            NULL_OFFSET,
            Spacing(),
            header,
            order=TOP_Z,
            fixed=True,
        ),
        WidgetPlacement(
            Region(0, 0, 80, 23), NULL_OFFSET, Spacing(), child, order=0, fixed=False
        ),
    ]
    assert result.widgets == {child, header}


async def test_arrange_dock_badly():
    child = Widget(id="child")
    child.styles.dock = "nowhere"
    with pytest.raises(AssertionError):
        _ = arrange(Widget(), [child], Size(80, 24), Size(80, 24))
