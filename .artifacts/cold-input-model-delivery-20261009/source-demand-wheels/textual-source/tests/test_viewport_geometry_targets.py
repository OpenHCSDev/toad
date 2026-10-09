import asyncio
from unittest.mock import patch

from textual import errors
from textual.app import App
from textual.containers import VerticalGroup, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static


def test_borrowed_geometry_routes_preserve_membership_ancestry_and_assignment_order():
    from types import MappingProxyType

    from textual._compositor import (
        IntrinsicSubtreeGeometry, PlacedSubtreeGeometry, RootSceneClip,
        SubtreeGeometryKey, SubtreeGeometryPlacement, SubtreeMapGeometry,
    )
    from textual.geometry import Offset, Region, Size, Spacing
    from textual.map_geometry import MapGeometry

    root, first, second, shared, logical, invisible, unrelated = (
        Static(name) for name in ("root", "first", "second", "shared", "logical", "invisible", "unrelated")
    )
    bounds = Region(0, 0, 20, 10)
    clip = RootSceneClip(bounds)
    key = SubtreeGeometryKey(0, 0, bounds, bounds, (), 0, bounds, True,
                            Spacing(), bounds.size, False, Offset(), ())

    def placed(owner, y, ancestors):
        region = Region(0, y, 5, 1)
        return MapGeometry(region, (), bounds, region.size, region.size, region,
                           Spacing(), ancestors, owner.gutter)

    def source(owner, y):
        return IntrinsicSubtreeGeometry(
            key, MappingProxyType({
                owner: (0, SubtreeMapGeometry(placed(owner, y, (root,)), (), None)),
                shared: (1, SubtreeMapGeometry(placed(shared, y + 1, (owner, root)), (), owner)),
            }), frozenset((owner, shared, logical)), frozenset((invisible,)),
        )

    first_source, second_source = source(first, 0), source(second, 5)
    resource = PlacedSubtreeGeometry(
        key, MappingProxyType({
            first: (0, SubtreeGeometryPlacement(first_source, key, clip, root)),
            second: (1, SubtreeGeometryPlacement(second_source, key, clip, root)),
            root: (2, placed(root, 9, ())),
        }), frozenset((root,)), frozenset(),
    )
    assert resource.contains(shared)
    assert logical in set(resource.members()) and not resource.contains(logical)
    assert invisible in set(resource.members(invisible=True)) and not resource.contains(invisible)
    assert not resource.contains(unrelated)
    assert resource._geometry_routes[shared] == (first, second)
    assert resource.captured_parent(shared) is first
    assert resource.captured_parent(first) is root
    published, clips = {}, {}
    resource.project_into(published, key, clip, clips, root, visible_only=True,
                          retained={shared, unrelated}, bounds=Region(30, 30, 1, 1),
                          ancestry_root=root, ancestors=())
    assert published[shared] == placed(shared, 6, (second, root))
    assert unrelated not in published


async def test_complete_markdown_capture_keeps_offscreen_table_keylines():
    from textual.widgets import Markdown
    from textual.widgets._markdown import MarkdownTableContent

    source = "\n\n".join(
        f"| key | value |\n| --- | --- |\n| TABLE_{index:02} | owned source |"
        for index in range(12)
    )
    body = Markdown(source)

    class TableScreen(Screen):
        def _use_viewport_layout(self):
            return True

        def compose(self):
            with VerticalScroll():
                yield body

    app = App()
    async with app.run_test(size=(60, 12)) as pilot:
        screen = TableScreen()
        await app.push_screen(screen)
        await pilot.pause()
        compositor = screen._compositor
        tables = list(body.query(MarkdownTableContent))
        assert len(tables) == 12
        assert tables[-1].outer_size.height == 0
        assert tables[-1] not in compositor._published_map
        _, placement = next(compositor.published_geometry((body,)))
        published = compositor._full_map, compositor._visible_map
        _, strips, _ = compositor.render_subtree_strips(body, placement)
        rows = [strip.text for strip in strips]
        for index in range(12):
            row = next(row for row in rows if f"TABLE_{index:02}" in row)
            assert "│" in row, f"Offscreen table {index} lost its captured keyline"
        assert compositor._full_map is published[0]
        assert compositor._visible_map is published[1]
        assert tables[-1].outer_size.height == 0


class TargetedScreen(Screen):
    CSS = "VerticalScroll { width: 1fr; } VerticalGroup, Static { height: auto; }"
    targets = ()

    def _use_viewport_layout(self):
        return True

    def _layout_geometry_targets(self):
        return self.targets

    def compose(self):
        with VerticalScroll(id="history"):
            for index in range(100):
                with VerticalGroup(id=f"group-{index}"):
                    yield Static(f"Row {index}: " + "wrapped text " * 10, id=f"row-{index}")
                    yield Static("second line " * 5)


async def test_held_complete_body_projects_original_scene_during_ancestor_scroll():
    """Real layout, paint and hit readers borrow the pre-mutation resource."""
    from textual._compositor import Compositor, IntrinsicSubtreeGeometry

    class HeldBody(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

        def arrange(self, size, optimal=False):
            assert not self.lock.is_locked, "Read changing body layout"
            return super().arrange(size, optimal=optimal)

    rows = [Static(f"COMMITTED_ROW_{index:02}", id=f"held-row-{index}")
            for index in range(40)]
    body = HeldBody(Static("FIXED_HEADER", id="held-heading"), *rows, id="held-body")

    class HeldScreen(TargetedScreen):
        CSS = """
        #held-heading { dock: top; height: 1; }
        #held-body Static { height: 2; }
        #outside-body { height: 30; }
        """

        def _layout_mutation_roots(self):
            return (body,) if body.lock.is_locked else ()

        def compose(self):
            with VerticalScroll(id="history"):
                yield body
                yield Static("\n".join(["OUTSIDE_BODY"] * 30), id="outside-body")

    app = App()
    async with app.run_test(size=(40, 10)) as pilot:
        screen = HeldScreen()
        screen.targets = (body,)
        await app.push_screen(screen)
        await pilot.pause()
        history = screen.query_one("#history", VerticalScroll)
        compositor = screen._compositor
        resource = compositor._subtree_geometry[body]
        assert isinstance(resource, IntrinsicSubtreeGeometry)
        assert all(resource.contains(row) for row in rows)
        # Holding revisions does not permit resizing or changing the source's
        # own scroll scope. Those answers still require a fresh arrangement.
        assert not resource.matches(
            resource.key._replace(region=resource.key.region.grow((0, 1, 0, 0))),
            source_held=True,
        )
        assert not resource.matches(
            resource.key._replace(scroll_offset=resource.key.scroll_offset + (0, 1)),
            source_held=True,
        )

        # Acquire the unchanged source at the real destination before mutation.
        # This is an ordinary compositor, not a reconstructed translation oracle.
        expected = {}
        for position in (0, 16, 4, 100):
            history.scroll_to(y=position, animate=False, immediate=True)
            await pilot.pause()
            reference = Compositor(max_subtree_geometry_entries=0)
            reference.reflow_visible(screen, app.size, retain_geometry=(body,))
            expected[position] = {
                node: geometry for node, geometry in reference._visible_map.items()
                if node is body or geometry.visible_region.overlaps(app.size.region)
            }
        history.scroll_to(y=0, animate=False, immediate=True)
        await pilot.pause()
        screen.targets = ()

        completed = asyncio.Event()
        unrelated = asyncio.Event()
        async with body.lock:
            incomplete = Static("UNCOMMITTED_CHILD", id="incomplete")
            await body.mount(incomplete)
            body.call_after_refresh(completed.set)
            screen.query_one("#outside-body").call_after_refresh(unrelated.set)
            await pilot.pause()
            for position in (16, 100, 4, 0):
                history.scroll_to(y=position, animate=False, immediate=True)
                await pilot.pause()
                assert compositor._subtree_geometry[body] is resource
                assert incomplete not in compositor._published_map
                for node, geometry in expected[position].items():
                    assert compositor._published_map[node] == geometry, (position, node.id)
                # Actual strip rendering and hit testing consume that same scene.
                strips = compositor.render_strips()
                rendered = "\n".join(strip.text for strip in strips)
                assert "UNCOMMITTED_CHILD" not in rendered
                if position == 100:
                    assert "COMMITTED_ROW" not in rendered
                    assert "OUTSIDE_BODY" in rendered
                else:
                    assert "COMMITTED_ROW" in rendered
                for row in rows:
                    geometry = compositor._published_map.get(row)
                    if geometry is not None and geometry.visible_region:
                        x, y = geometry.visible_region.offset
                        hit, _ = compositor.get_widget_at(x, y)
                        assert hit is row
                        break
            assert not completed.is_set()
            assert unrelated.is_set()

        body.refresh(layout=True)
        await pilot.pause()
        assert compositor._subtree_geometry[body] is not resource
        assert incomplete in compositor.widgets
        assert completed.is_set()
        assert not app._exception


async def test_held_screen_relative_source_keeps_placement_and_retires_children():
    from textual._compositor import PlacedSubtreeGeometry

    class HeldBody(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

        def arrange(self, size, optimal=False):
            assert not self.lock.is_locked, "Read changing overlay layout"
            return super().arrange(size, optimal=optimal)

    overlay = Static("SCREEN_OVERLAY", id="overlay")
    retired = Static("RETIRE_THIS", id="retired")
    body = HeldBody(overlay, retired, *(Static(f"row {i}") for i in range(30)))

    class HeldScreen(TargetedScreen):
        CSS = "#overlay { overlay: screen; width: 12; height: 1; offset: 2 3; }"

        def compose(self):
            with VerticalScroll(id="history"):
                yield body

        def _layout_mutation_roots(self):
            return (body,) if body.lock.is_locked else ()

    app = App()
    async with app.run_test(size=(40, 10)) as pilot:
        screen = HeldScreen()
        screen.targets = (body,)
        await app.push_screen(screen)
        await pilot.pause()
        compositor = screen._compositor
        resource = compositor._subtree_geometry[body]
        assert isinstance(resource, PlacedSubtreeGeometry)
        original = dict(compositor._published_map)
        async with body.lock:
            await body.mount(Static("INCOMPLETE"))
            screen.query_one("#history").scroll_to(y=10, animate=False, immediate=True)
            await pilot.pause()
            for node, geometry in original.items():
                if resource.contains(node):
                    assert compositor._published_map[node] == geometry
            await retired.remove()
            await pilot.pause()
            assert body not in compositor._subtree_geometry
            assert retired not in compositor._published_map
            assert retired not in compositor.widgets
            assert compositor._published_map[overlay] == original[overlay]
        body.refresh(layout=True)
        await pilot.pause()
        assert not app._exception


async def test_held_original_ancestry_honors_a_nested_self_painting_owner():
    from textual.content import Content

    class HeldGroup(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

        def arrange(self, size, optimal=False):
            assert not self.lock.is_locked, "Read changing child topology"
            return super().arrange(size, optimal=optimal)

    class ContentBody(Static):
        # This application declares a native child view for its initial text
        # and a self-painted view when it acquires its actual Content resource.
        @property
        def is_container(self):
            return not isinstance(self.content, Content)

    holder = HeldGroup(id="holder")

    class ChangingChild(Static):
        def render_lines(self, crop):
            assert not holder.lock.is_locked, "Read changing descendant paint"
            return super().render_lines(crop)

    body = ContentBody("INITIAL_NATIVE_PARENT", id="content-body")
    old = ChangingChild("OLD_NATIVE_CHILD")

    class ContentScreen(TargetedScreen):
        CSS = "#content-body { height: 18; } Static { height: 2; }"

        def compose(self):
            with VerticalScroll(id="history"):
                yield holder

        def _layout_mutation_roots(self):
            return (holder,) if holder.lock.is_locked else ()

    app = App()
    async with app.run_test(size=(40, 10)) as pilot:
        screen = ContentScreen()
        screen.targets = (holder,)
        await app.push_screen(screen)
        await holder.mount(body)
        await body.mount(old)
        await pilot.pause()
        compositor = screen._compositor
        resource = compositor._subtree_geometry[holder]
        assert resource.contains(old)
        assert resource.captured_parent(old) is body
        async with holder.lock:
            body.update(Content("\n".join(["ACQUIRED_ROOT_PAINT"] * 18)))
            await body.mount(ChangingChild("UNCOMMITTED_DESCENDANT"))
            screen.query_one("#history").scroll_to(y=4, animate=False, immediate=True)
            await pilot.pause()
            assert compositor._subtree_geometry[holder] is resource
            assert old not in compositor._published_map
            assert body in compositor._published_map
            painted = "\n".join(strip.text for strip in compositor.render_strips())
            assert "ACQUIRED_ROOT_PAINT" in painted
            assert "OLD_NATIVE_CHILD" not in painted
            assert "UNCOMMITTED_DESCENDANT" not in painted
        holder.refresh(layout=True)
        await pilot.pause()
        assert not app._exception


async def test_cached_overlay_and_fixed_children_match_the_original_scene():
    from textual._compositor import Compositor, PlacedSubtreeGeometry

    class CachedBody(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

    body = CachedBody(
        Static("Fixed heading", id="fixed-heading"),
        Static("Screen overlay", id="screen-overlay"),
        *(Static(f"Source row {index}", id=f"source-row-{index}") for index in range(80)),
        id="cached-body",
    )

    class OverlayScreen(TargetedScreen):
        CSS = """
        #fixed-heading { dock: top; height: 1; }
        #screen-overlay { overlay: screen; width: 15; height: 1; offset: 5 3; }
        """

        def compose(self):
            with VerticalScroll(id="history"):
                yield body

    app = App()
    async with app.run_test(size=(40, 10)) as pilot:
        screen = OverlayScreen()
        screen.targets = (body,)
        await app.push_screen(screen)
        await pilot.pause()
        history = screen.query_one("#history", VerticalScroll)
        compositor = screen._compositor
        for position in (0, 30, 0):
            history.scroll_to(y=position, immediate=True, animate=False)
            screen._refresh_layout(app.size, scroll=True)
            # The overlay's clip reaches the outer screen, so this resource
            # keeps placed geometry rather than manufacturing an intrinsic clip.
            assert isinstance(compositor._subtree_geometry[body], PlacedSubtreeGeometry)
            expected, _ = Compositor(max_subtree_geometry_entries=0)._arrange_root(
                screen, app.size, visible_only=False,
            )
            paint = compositor._paint_regions(compositor._ordered_geometry(expected), app.size.region)
            admitted = {node: expected[node] for node in paint}
            admitted[body] = expected[body]  # The original explicit geometry target.
            for node, entry in admitted.items():
                assert node in compositor._visible_map, (position, node.id, entry)
                assert compositor._visible_map[node] == entry
            actual_layers = compositor._ordered_geometry(compositor._visible_map)
            expected_layers = compositor._ordered_geometry(expected)
            assert [(node, entry) for node, entry in actual_layers if node in admitted] == [
                (node, entry) for node, entry in expected_layers if node in admitted
            ]


async def test_complete_cached_body_keeps_capture_and_explicit_reader_geometry():
    class CachedBody(VerticalGroup):
        CACHE_SUBTREE_GEOMETRY = True

    rows = [Static(f"Original row {index}", id=f"cached-row-{index}")
            for index in range(240)]
    body = CachedBody(*rows, id="cached-body")

    class CachedScreen(TargetedScreen):
        def compose(self):
            with VerticalScroll(id="history"):
                yield body

    app = App()
    async with app.run_test(size=(40, 10)) as pilot:
        screen = CachedScreen()
        screen.targets = (body, rows[235])
        await app.push_screen(screen)
        await pilot.pause()
        history = screen.query_one("#history", VerticalScroll)
        compositor = screen._compositor
        resource = compositor._subtree_geometry[body]
        assert all(resource.contains(row) for row in rows)

        for position in (0, 200, 0):
            history.scroll_to(y=position, immediate=True, animate=False)
            screen._refresh_layout(app.size, scroll=True)
            viewport = compositor._visible_map
            assert body in viewport and rows[235] in viewport
            omitted = rows[200] if position == 0 else rows[0]
            assert omitted not in viewport
            assert all(resource.contains(row) for row in rows)
            assert all(row in compositor.widgets for row in rows)
            _, placement = next(compositor.published_geometry((body,)))
            source_bounds = app.size.region - (placement.region.offset - resource.key.region.offset)
            candidates = resource._spatial_map.get_values_in_region(source_bounds)
            # The immutable source stays complete; spatial admission and the
            # explicit offscreen reader path remain different original facts.
            assert omitted not in {node for _, node in candidates}
            assert rows[235] not in {node for _, node in candidates}
            assert len(candidates) < len(resource.geometry)
            # Capture remains complete without replacing the published viewport.
            size, strips, _ = compositor.render_subtree_strips(body, placement)
            assert size.height == 240
            assert all(f"Original row {index}" in strip.text
                       for index, strip in enumerate(strips))
            assert compositor._visible_map is viewport

        # A position query retains its path without requiring every offscreen row.
        assert compositor.find_widget(rows[20]).region.height == 1
        assert rows[20] in compositor._visible_map
        assert rows[235] in compositor._visible_map
        assert compositor._full_map_invalidated
        assert all(row in compositor.full_map for row in rows)
        rows[5].display = False
        await pilot.pause()
        screen._refresh_layout(app.size, scroll=True)
        assert rows[5] not in compositor._subtree_geometry[body].geometry
        assert rows[235] in compositor._visible_map


async def test_offscreen_targets_match_full_geometry_without_full_tree_traversal():
    app = App()
    async with app.run_test(size=(80, 25)) as pilot:
        screen = TargetedScreen()
        await app.push_screen(screen)
        await pilot.pause()
        history = screen.query_one("#history", VerticalScroll)
        target = screen.query_one("#row-85", Static)
        screen.targets = (target,)
        for width, scroll in ((80, 0), (55, 30), (100, 250), (65, 0)):
            await pilot.resize_terminal(width, 25)
            history.scroll_to(y=scroll, immediate=True, animate=False)
            screen.refresh(layout=True)
            await pilot.pause()
            # Both layout and scrolling retain the original declared boxes.
            screen._refresh_layout(app.size)
            compositor = screen._compositor
            # Scrolling consumes the same original target declaration. Its
            # fast path must not discard the offscreen box just established.
            with patch.object(compositor, "reflow_visible", wraps=compositor.reflow_visible) as scroll_reflow:
                screen._refresh_layout(app.size, scroll=True)
                assert scroll_reflow.call_count == 1
            assert target in compositor._visible_map
            assert screen.query_one("#row-50") not in compositor._visible_map
            assert len(compositor._visible_map) < 80
            with patch.object(compositor, "_arrange_root", side_effect=AssertionError("Anchor query rebuilt all geometry")):
                actual_target = compositor.find_widget(target)
                rendered = tuple(tuple(strip) for strip in compositor.render_strips())
            compositor.reflow(screen, app.size)
            expected_target = compositor.find_widget(target)
            assert actual_target.region == expected_target.region
            assert actual_target.virtual_region == expected_target.virtual_region
            assert rendered == tuple(tuple(strip) for strip in compositor.render_strips())


async def test_foreign_and_removed_targets_do_not_enter_the_scene():
    app = App()
    async with app.run_test() as pilot:
        screen = TargetedScreen()
        await app.push_screen(screen)
        await pilot.pause()
        target = screen.query_one("#row-85")
        await target.remove()
        foreign = Static("foreign")
        screen.targets = (target, foreign)
        screen._refresh_layout(app.size)
        screen._refresh_layout(app.size, scroll=True)
        assert target not in screen._compositor._visible_map
        assert foreign not in screen._compositor._visible_map
        assert not tuple(screen._compositor.published_geometry((target, foreign)))


async def test_capture_requires_publication_while_position_queries_acquire_reader_paths():
    app = App()
    async with app.run_test(size=(80, 25)) as pilot:
        screen = TargetedScreen()
        await app.push_screen(screen)
        await pilot.pause()
        body = screen.query_one("#group-85", VerticalGroup)
        screen._refresh_layout(app.size)
        compositor = screen._compositor
        assert body.is_mounted and body not in compositor._visible_map
        published = compositor._full_map, compositor._visible_map
        with patch.object(compositor, "_arrange_root", side_effect=AssertionError("Capture manufactured a full scene")):
            assert not tuple(compositor.published_geometry((body,)))
        assert compositor._full_map is published[0]
        assert compositor._visible_map is published[1]
        # Position queries acquire this original path in the current scene.
        assert compositor.find_widget(body).region.height > 0
        assert body in compositor._visible_map
        assert screen.query_one("#group-50") not in compositor._visible_map
        assert compositor._full_map is published[0]
        assert compositor._full_map_invalidated


async def test_body_capture_descendants_use_original_arrangement_and_screen_coordinates():
    app = App()
    async with app.run_test(size=(80, 25)) as pilot:
        screen = TargetedScreen()
        await app.push_screen(screen)
        await pilot.pause()
        body = screen.query_one("#group-85", VerticalGroup)
        row = screen.query_one("#row-85", Static)
        screen.targets = (body,)
        screen._refresh_layout(app.size)
        compositor = screen._compositor
        published_body, placement = next(compositor.published_geometry((body,)))
        assert published_body is body
        bounds = placement.region
        assert row not in compositor._visible_map
        published = compositor._full_map, compositor._visible_map
        arrange = compositor._arrange_root
        rendered_regions = []
        render_lines = row.render_lines

        def arrange_body(root, *args, **kwargs):
            assert root is body, "Body rendering rebuilt the whole screen"
            return arrange(root, *args, **kwargs)

        def render_row(crop):
            rendered_regions.append(row.region)
            return render_lines(crop)

        with patch.object(compositor, "_arrange_root", side_effect=arrange_body), patch.object(row, "render_lines", side_effect=render_row):
            size, strips, _ = compositor.render_subtree_strips(body, placement)
        assert size == bounds.size
        assert len(strips) == size.height
        assert all(strip.cell_length == size.width for strip in strips)
        assert "Row 85" in "\n".join(strip.text for strip in strips)
        assert "second line" in "\n".join(strip.text for strip in strips)
        assert rendered_regions and all(region.offset == bounds.offset for region in rendered_regions)
        assert compositor._full_map is published[0]
        assert compositor._visible_map is published[1]
        assert compositor._render_geometry is None

        # A descendant omitted by its real display rule must remain absent
        # inside capture, rather than acquiring geometry from the outer scene.
        hidden = body.children[1]
        hidden.display = False
        await pilot.pause()
        screen._refresh_layout(app.size)
        _, placement = next(compositor.published_geometry((body,)))
        published = compositor._full_map, compositor._visible_map
        scoped_misses = []

        def render_with_hidden_query(crop):
            try:
                compositor.find_widget(hidden)
            except errors.NoWidget:
                scoped_misses.append(hidden)
            else:
                raise AssertionError("Hidden capture descendant escaped its original arrangement")
            return render_lines(crop)

        with patch.object(compositor, "_arrange_root", side_effect=arrange_body), patch.object(row, "render_lines", side_effect=render_with_hidden_query):
            compositor.render_subtree_strips(body, placement)
        assert scoped_misses
        assert compositor._render_geometry is None
        assert compositor._full_map is published[0]
        assert compositor._visible_map is published[1]

        # A failing renderer must release the same scoped resource and leave
        # ordinary screen queries with their original publication.
        with patch.object(row, "render_lines", side_effect=ValueError("render failed")):
            try:
                compositor.render_subtree_strips(body, placement)
            except ValueError as error:
                assert str(error) == "render failed"
            else:
                raise AssertionError("Renderer failure was hidden")
        assert compositor._render_geometry is None
        assert compositor._full_map is published[0]
        assert compositor._visible_map is published[1]
