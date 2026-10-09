"""Old-scene damage must be projected into the admitted render frame."""
import pytest
from textual.app import App
from textual.geometry import Size
from textual.widgets import Static


async def test_completed_chops_preserve_partial_and_held_paint():
    from textual.geometry import Region

    class CoveredApp(App):
        CSS = """
        Screen { layers: back front; }
        #back { layer: back; width: 100%; height: 100%; }
        #front { layer: front; width: 100%; height: 100%; }
        """

        def compose(self):
            yield Static("background", id="back")
            yield Static("[bold]foreground 界[/bold]", id="front")

    app = CoveredApp()
    async with app.run_test(size=(24, 8)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        reference = compositor.render_strips()
        assert "foreground" in reference[0].text
        assert not any("background" in strip.text for strip in reference)
        compositor._dirty_regions = {Region(0, 0, 24, 2)}
        held = Region(3, 0, 5, 1)
        update = compositor.render_partial_update(excluded_regions=(held,))
        assert update is not None
        for y, left, right in update.spans:
            assert not Region(left, y, right - left, 1).overlaps(held)
            for x, strip in update._get_line_chops(y, left, right):
                assert strip == reference[y].crop(x, x + strip.cell_length)
        assert compositor._dirty_regions == {held}
        released = compositor.render_partial_update()
        assert released is not None
        assert compositor._dirty_regions == set()
        assert compositor.render_partial_update() is None
        assert compositor.render_strips() == reference

@pytest.mark.parametrize('before,after', [(Size(139,40),Size(139,25)),(Size(80,40),Size(30,12)),(Size(30,12),Size(80,40))])
async def test_partial_damage_uses_current_frame_for_spans_and_chops(before,after):
    class FrameApp(App):
        def compose(self):
            yield Static('\n'.join(f'FRAME_CONTENT_{i}' for i in range(60)))
    app=FrameApp()
    async with app.run_test(size=tuple(before)) as pilot:
        await pilot.pause()
        compositor=app.screen._compositor
        compositor.reflow(app.screen,after)
        update=compositor.render_partial_update()
        assert update is not None
        assert len(update.chops)==len(update.cuts)==after.height
        assert all(0<=y<after.height and 0<=left<right<=after.width for y,left,right in update.spans)
        assert 'FRAME_CONTENT' in update.render_segments(app.console)

async def test_lazy_full_geometry_preserves_old_caption_damage():
    from textual.screen import Screen
    from textual.widgets import Label
    from textual.containers import VerticalGroup

    class CaptionScreen(Screen):
        CSS = """
        #prompt { dock: bottom; height: auto; }
        #controls { display: none; height: 1; }
        """

        def _use_viewport_layout(self):
            return True

        def compose(self):
            with VerticalGroup(id='prompt'):
                yield Label('Submitting: ORIGINAL_INPUT', id='caption')
                yield Label('Enter queues', id='controls')
                yield Label('Editor')

    app = App()
    async with app.run_test(size=(60, 12)) as pilot:
        screen = CaptionScreen()
        await app.push_screen(screen)
        await pilot.pause()
        compositor = screen._compositor
        caption = screen.query_one('#caption', Label)
        previous = caption.region
        assert compositor._visible_map is not None
        compositor._dirty_regions.clear()
        screen.query_one('#controls', Label).display = True
        caption.update('Queued: ORIGINAL_INPUT')
        # This is the native lazy geometry lookup, before the next timer reflow.
        current = compositor.full_map[caption].region
        assert current.y == previous.y - 1
        update = compositor.render_partial_update()
        assert update is not None
        assert any(y == previous.y and left <= previous.x < right
                   for y, left, right in update.spans), 'Old caption row lost its damage'
        assert any(y == current.y and left <= current.x < right
                   for y, left, right in update.spans)


def test_both_chop_writers_preserve_wide_cell_clipping_and_metadata():
    """A damage edge inside a wide cell must not overwrite its untouched half."""
    from rich.console import Console
    from rich.control import Control
    from rich.segment import Segment
    from rich.style import Style
    from textual._compositor import ChopsUpdate
    from textual.strip import Strip

    style = Style(meta={"owner": "original"})
    update = ChopsUpdate(
        [{0: Strip([Segment("A界BCD", style)], 6)}],
        [(0, 2, 5)],
        [[0, 6]],
    )
    console = Console(force_terminal=True, color_system="truecolor")
    rich_segments = list(update.__rich_console__(console, console.options))
    assert rich_segments[0] == Control.move_to(2, 0).segment
    content = [segment for segment in rich_segments if not segment.control]
    assert "".join(segment.text for segment in content) == " BC"
    assert all(segment.style.meta == {"owner": "original"} for segment in content)
    assert update.render_segments(console) == Control.move_to(2, 0).segment.text + " BC"


async def test_sparse_damage_publishes_only_selected_native_rows():
    from textual.geometry import Region

    class SparseApp(App):
        def compose(self):
            yield Static("\n".join("ABCDEFGHIJKLM" for _ in range(12)))

    app = SparseApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        cuts = compositor.cuts
        compositor._dirty_regions = {Region(2, 1, 3, 1), Region(4, 8, 2, 1)}
        update = compositor.render_partial_update()
        assert update.cuts is cuts
        assert {y for y, row in enumerate(update.chops) if row} == {1, 8}
        segments = list(update.__rich_console__(app.console, app.console.options))
        assert "".join(segment.text for segment in segments if not segment.control) == "CDE\nEF"


@pytest.mark.parametrize('regions', [
    ((2, 0, 3, 1), (22, 0, 3, 1)),
    ((1, 0, 2, 1), (2, 0, 3, 1), (21, 2, 2, 1)),
])
async def test_horizontal_damage_keeps_intervening_native_content_unpainted(regions):
    """Damage islands must not materialize the unchanged pane between them."""
    from rich.control import Control
    from textual.geometry import Region

    class Counted(Static):
        def __init__(self, **kwargs):
            super().__init__("[link='https://example.com']A界BCDEFGH[/link]\nSECOND\nTHIRD", **kwargs)
            self.crops = []

        def render_lines(self, crop):
            self.crops.append(crop)
            return super().render_lines(crop)

    class IslandsApp(App):
        CSS = "Screen { layout: horizontal; } Counted { width: 10; height: 3; }"

        def compose(self):
            for name in ('left', 'middle', 'right'):
                yield Counted(id=name)

    app = IslandsApp()
    async with app.run_test(size=(30, 5)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        reference = compositor.render_strips()
        panes = [app.query_one(f'#{name}', Counted) for name in ('left', 'middle', 'right')]
        for pane in panes:
            pane.crops.clear()
        compositor._dirty_regions = {Region(*region) for region in regions}
        update = compositor.render_partial_update()
        assert update is not None
        assert panes[0].crops and panes[2].crops
        assert panes[1].crops == []
        assert all(not region.translate(pane.region.offset).overlaps(panes[1].region)
                   for pane in (panes[0], panes[2]) for region in pane.crops)

        expected = []
        for y, x1, x2 in update.spans:
            painted = list(update._get_line_chops(y, x1, x2))
            assert len(painted) == 1
            x, strip = painted[0]
            assert x == x1
            assert strip == reference[y].crop(x1, x2)
            expected.append(Control.move_to(x1, y).segment.text + strip.render(app.console))
            if y != update.spans[-1][0]:
                expected.append('\n')
        assert update.render_segments(app.console) == ''.join(expected)


async def test_body_capture_keeps_original_nonzero_row_coordinates():
    class BodyApp(App):
        CSS = "#body { width: 12; height: 3; offset: 5 4; }"

        def compose(self):
            yield Static("ABC界DEF\nSECOND_ROW\nTHIRD_ROW", id="body")

    app = BodyApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        body = app.query_one("#body")
        [(original, placement)] = list(compositor.published_geometry([body]))
        assert placement.region.y == 4
        size, strips, _ = compositor.render_subtree_strips(original, placement)
        assert size == Size(12, 3)
        assert [strip.text.rstrip() for strip in strips] == ["ABC界DEF", "SECOND_ROW", "THIRD_ROW"]

        # Capturing a partly offscreen body still owns its full original rows.
        # Native screen painting clips it; capture has distinct nonzero bounds.
        from textual.geometry import Region
        body.styles.offset = (-2, -1)
        await pilot.pause()
        [(original, placement)] = list(compositor.published_geometry([body]))
        assert placement.region == Region(-2, -1, 12, 3)
        assert compositor.visible_widgets[body] == (
            placement.region, Region(0, 0, 10, 2),
        )
        geometry, _ = compositor._arrange_root(
            original, compositor.size, visible_only=False, root_geometry=placement,
        )
        paint = compositor._paint_regions(compositor._ordered_geometry(geometry), placement.region)
        assert paint[body] == (placement.region, placement.region)
        assert compositor._cuts_for_regions(placement.region, paint) == [[-2, 10]] * 3
        size, strips, _ = compositor.render_subtree_strips(original, placement)
        assert size == Size(12, 3)
        assert [strip.text.rstrip() for strip in strips] == ["ABC界DEF", "SECOND_ROW", "THIRD_ROW"]


async def test_scene_change_retains_both_rectangles_and_widget_size_publication():
    """Movement, resizing, hide and show consume original native scene records."""
    from textual.geometry import Region

    class SceneApp(App):
        CSS = "#box { width: 8; height: 2; offset: 2 1; }"

        def compose(self):
            yield Static("SOURCE", id="box")

    app = SceneApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        box = app.query_one("#box")
        assert box.region == Region(2, 1, 8, 2)
        compositor._dirty_regions.clear()
        box.styles.width = 12
        box.styles.offset = (4, 3)
        result = compositor.reflow(app.screen, Size(40, 12))
        placement = compositor.find_widget(box)
        assert box._size_updated(
            placement.region.size, placement.virtual_size, placement.container_size
        )
        assert {Region(2, 1, 8, 2), Region(4, 3, 12, 2)} <= compositor._dirty_regions

        compositor._dirty_regions.clear()
        box.display = False
        result = compositor.reflow(app.screen, Size(40, 12))
        assert box in result.hidden
        assert box.outer_size == Size(12, 2)
        assert Region(4, 3, 12, 2) in compositor._dirty_regions

        compositor._dirty_regions.clear()
        box.display = True
        result = compositor.reflow(app.screen, Size(40, 12))
        assert box in result.shown
        placement = compositor.find_widget(box)
        assert not box._size_updated(
            placement.region.size, placement.virtual_size, placement.container_size
        )
        assert Region(4, 3, 12, 2) in compositor._dirty_regions


async def test_capture_geometry_and_offsets_share_original_scene_custody():
    """Offset queries must not arrange another scene or admit an omitted child."""
    from textual import errors
    from textual.containers import Vertical

    class CaptureApp(App):
        CSS = """
        #body { width: 12; height: 4; offset: 5 2; }
        #spacer { height: 8; }
        #far { height: 1; }
        #omitted { display: none; }
        #outside { dock: bottom; height: 1; }
        """

        def compose(self):
            with Vertical(id="body"):
                yield Static("SPACER", id="spacer")
                yield Static("CAPTURE_ONLY", id="far")
                yield Static("OMITTED", id="omitted")
            yield Static("OTHER_SCENE", id="outside")

    app = CaptureApp()
    async with app.run_test(size=(40, 12)) as pilot:
        await pilot.pause()
        compositor = app.screen._compositor
        body, far, omitted, outside = (
            app.query_one(f"#{name}") for name in ("body", "far", "omitted", "outside")
        )
        compositor.reflow_visible(app.screen, Size(40, 12), retain_geometry=())
        publication = compositor._visible_map
        assert far not in publication
        [(original, placement)] = compositor.published_geometry((body,))
        capture, _ = compositor._arrange_root(
            original, compositor.size, visible_only=False, root_geometry=placement,
        )
        assert far in capture and omitted not in capture

        with compositor._using_geometry(body, capture):
            assert compositor.find_widget(far) is capture[far]
            assert app.screen.get_offset(far) == capture[far].region.offset
            assert far.region == capture[far].region
            assert app.screen.get_offset(outside) == publication[outside].region.offset
            for read in (compositor.find_widget, app.screen.get_offset):
                with pytest.raises(errors.NoWidget):
                    read(omitted)
            assert compositor._visible_map is publication
            assert compositor._full_map_invalidated

            # A failed nested paint must restore the enclosing original resource.
            nested, _ = compositor._arrange_root(
                far, compositor.size, visible_only=False, root_geometry=capture[far],
            )
            with pytest.raises(RuntimeError, match="native renderer failed"):
                with compositor._using_geometry(far, nested):
                    assert compositor.find_widget(far) is nested[far]
                    assert app.screen.get_offset(far) == nested[far].region.offset
                    raise RuntimeError("native renderer failed")
            assert compositor.find_widget(far) is capture[far]

        assert compositor._render_geometry is None
        # An offscreen query acquires its path without escaping captured scopes
        # or forcing a complete native scene.
        assert compositor.find_widget(far).region == capture[far].region
        assert far in compositor._visible_map
        assert compositor._full_map_invalidated
