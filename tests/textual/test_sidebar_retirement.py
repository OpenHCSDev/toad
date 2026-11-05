"""Textual-facing: a thread sidebar's optional panels are released and rebuilt with their selection, scroll and plan state, and the rich widget graph is collected; collection asserts cover panels built after the first history's freeze (DECISIONS.md 2026-10-11)."""

import asyncio
import gc
from weakref import ref

from agent_comms.repo import Checkout
from agent_comms.relationships import (
    AddRelationshipEdit,
    CollaboratingRelationshipGroup,
)
from support.ui import saved_tab
from textual.screen import Screen

from toad.app import HeapFrozen, ToadApp
from toad.plan import InProgressPlanStatus, PlanItem
from toad.screens.main import MainScreen
from toad.widgets.plan import Plan
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import PanelHydration, SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.project_panel import NO_PROJECT_VIEW
from toad.widgets.project_tree_intent import NO_TREE_INTENT


def viewport_text(widget):
    """Crop actual compositor strips to the visible native widget viewport."""
    region, clip = widget.screen.screen._compositor.visible_widgets[widget]
    region = region.intersection(clip).intersection(widget.screen.region)
    return "\n".join(
        strip.crop(region.x, region.right).text
        for strip in widget.screen.screen._compositor.render_strips()[
            region.y : region.bottom
        ]
    )


def project_with_files(workspace):
    (workspace.project / "folder/deep").mkdir(parents=True)
    for index in range(48):
        (workspace.project / "folder/deep" / f"item-{index:02}.txt").write_text(
            str(index)
        )
    for name in ("owner", "peer"):
        workspace.thread(name)
    workspace.comms.relationships.edit(
        "owner", AddRelationshipEdit, "peer", "Actual relationship"
    )


async def started(workspace, ui):
    screen = ui.app.selected_session
    await workspace.bind(screen, "owner")
    await ui.until(
        lambda: isinstance(ui.app.heap, HeapFrozen),
        seconds=12,
        why="the heap's one freeze",
    )
    return screen


async def reveal(ui, screen):
    sidebar = screen.query_one(SessionThreadSidebar)
    sidebar.reveal()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await ui.step(0.02)
    return sidebar


async def prepare_project(ui, sidebar):
    sidebar.query_one("#project-panel", SideBarCollapsible).collapsed = False
    await ui.until(
        lambda: sidebar.query_one_optional(ProjectDirectoryTree) is not None,
        seconds=12,
        why="the project tree",
    )
    tree = sidebar.query_one(ProjectDirectoryTree)
    await ui.until(
        lambda: tree.path_filter is not None and not tree._load_queue._unfinished_tasks,
        seconds=12,
        why="the project tree to load",
    )
    await ui.step(0.02)
    return tree


async def exercise(ui, screen, root):
    sidebar = await reveal(ui, screen)
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await ui.until(
        lambda: CollaboratingRelationshipGroup in relationships.groups,
        seconds=12,
        why="the collaborating group",
    )
    group = relationships.groups[CollaboratingRelationshipGroup]
    if not group.expanded:
        group.toggle_members()
    await ui.until(
        lambda group=group: bool(group.rows), seconds=12, why="the collaborating rows"
    )
    row = next(iter(group.rows.values()))
    relationships.remember_row(row)
    chosen = relationships.selection_for(row)
    assert chosen[0] is CollaboratingRelationshipGroup and row.entry.target == "peer"
    if group.expanded:
        group.toggle_members()
    await ui.step(0.02)
    tree = await prepare_project(ui, sidebar)
    folder = next(
        node for node in tree.root.children if node.data.path == root / "folder"
    )
    folder.expand()
    await tree._add_to_load_queue(folder)
    deep = next(
        node for node in folder.children if node.data.path == root / "folder/deep"
    )
    deep.expand()
    await tree._add_to_load_queue(deep)
    selected = next(
        node for node in deep.children if node.data.path.name == "item-38.txt"
    )
    tree.move_cursor(selected, animate=False)
    tree.scroll_to(y=12, animate=False, immediate=True)
    viewport = sidebar.panels_viewport
    viewport.scroll_to(y=3, animate=False, immediate=True)
    await ui.step(0.02)
    state = relationships.view_state
    tree_scroll, panel_scroll = tree.scroll_y, viewport.scroll_y
    assert state.selected == chosen
    saved = [ref(panel.widget) for panel in sidebar.panels]
    tree_ref = ref(tree)
    await sidebar.retire_presentation(screen)
    assert all(
        widget() is panel.widget
        for widget, panel in zip(saved, sidebar.panels, strict=True)
    )
    assert tree_ref() is sidebar.query_one(ProjectDirectoryTree)
    await sidebar.prepare_presentation()
    assert tree_ref() is sidebar.query_one(ProjectDirectoryTree)
    await sidebar.evict(screen)
    assert not sidebar.panels and not sidebar.panels_loaded
    assert screen._project_panel is NO_PROJECT_VIEW
    assert not tuple(viewport.children)
    assert not sidebar.query(Plan) and not sidebar.query(ThreadCommsSidebar)
    del relationships, tree, row, group, selected, folder, deep
    await ui.step(0.05)
    gc.collect()
    assert all(widget() is None for widget in saved), (
        "Retired panel graph remains reachable"
    )
    assert tree_ref() is None, "Retired DirectoryTree remains reachable"
    latest = [PlanItem("Latest while absent", "high", InProgressPlanStatus)]
    sidebar.update_plan(latest)
    await sidebar.prepare_presentation()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await ui.step(0.02)
    assert sidebar.query_one(Plan).entries is latest
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await ui.until(
        lambda: CollaboratingRelationshipGroup in relationships.groups,
        seconds=12,
        why="the collaborating group after rebuild",
    )
    assert relationships.view_state is state
    assert state.selected == chosen
    assert not relationships.groups[CollaboratingRelationshipGroup].expanded
    tree = await prepare_project(ui, sidebar)
    await ui.until(
        lambda: (
            tree.cursor_node is not None
            and tree.cursor_node.data.path == root / "folder/deep/item-38.txt"
        ),
        seconds=12,
        why="the project tree cursor to be restored",
    )
    await ui.until(
        lambda: screen._project_panel._intent is NO_TREE_INTENT,
        seconds=12,
        why="the project panel to settle",
    )
    assert tree.scroll_y == tree_scroll, (
        tree.scroll_y,
        tree_scroll,
        tree.size,
        tree.virtual_size,
    )
    assert viewport.scroll_y == panel_scroll, (viewport.scroll_y, panel_scroll)
    assert all(word in viewport_text(sidebar) for word in ("Latest", "while", "absent"))
    tree.scroll_visible(animate=False, immediate=True)
    tree.scroll_to(y=tree.max_scroll_y, animate=False, immediate=True, force=True)
    await ui.step(0.02)
    assert "item-38.txt" in viewport_text(tree), (
        "Restored filename was not actually painted",
        viewport_text(tree),
    )


async def test_panels_restore_selection_scroll_and_plan_after_release_and_collect_the_old_widgets(
    workspace,
):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        screen = await started(workspace, ui)
        for _ in range(3):
            await exercise(ui, screen, workspace.project)


async def test_panels_rebuild_after_eviction_while_collapsed(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        screen = await started(workspace, ui)
        sidebar = screen.query_one(SessionThreadSidebar)
        await sidebar.evict(screen)
        sidebar.reveal()
        sidebar.collapsed = True
        await ui.step(0.05)
        assert not sidebar.panels
        sidebar.reveal()
        await sidebar.wait_content_ready()
        assert len(sidebar.panels) == len(sidebar._panel_owners)


async def test_panels_show_the_current_project_after_the_source_project_changes_while_released(
    workspace,
):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        await sidebar.evict(screen)
        replacement = workspace.project.parent / "replacement-project"
        replacement.mkdir()
        (replacement / "new-source.txt").write_text("Current filesystem")
        screen.project_path = Checkout(replacement)
        await sidebar.prepare_presentation()
        await sidebar.wait_content_ready()
        tree = await prepare_project(ui, sidebar)
        assert tree.path == replacement or str(tree.path) == str(replacement)
        assert not any(node.data.path.name == "folder" for node in tree.root.children)
        tree.scroll_visible(animate=False, immediate=True)
        await ui.step(0.02)
        assert "new-source.txt" in viewport_text(tree)


async def test_leaving_a_view_stops_its_sidebar_hydration(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        app, _ = ui.textual
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        # The next tab is saved first, so leaving the view does not wait on the database.
        tab = await saved_tab(app)
        await sidebar.evict(screen)
        sidebar._start_hydration()
        workers = tuple(
            worker
            for worker in sidebar.workers
            if worker.node is sidebar and worker.group == PanelHydration.group
        )
        assert workers
        await asyncio.sleep(0)
        await app.session_navigation.new(tab, lambda: MainScreen(app.project_dir))
        await ui.step(0.02)
        # Retirement either keeps a load that finished or releases one that didn't
        # (session_thread_sidebar.retire_presentation); it never keeps half of one.
        assert len(sidebar.panels) in (0, len(sidebar._panel_owners))
        assert sidebar.panels_loaded == bool(sidebar.panels)
        assert all(worker.is_finished for worker in workers)
        await app.select_session(screen.id)
        await sidebar.wait_content_ready()
        assert len(sidebar.panels) == len(sidebar._panel_owners)


async def test_an_opaque_screen_over_a_loading_sidebar_leaves_it_whole(workspace):
    """Covering the workspace mid-load must not strand panels without their controls."""
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        app, _ = ui.textual
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        await sidebar.evict(screen)
        sidebar._start_hydration()
        workers = tuple(
            worker
            for worker in sidebar.workers
            if worker.node is sidebar and worker.group == PanelHydration.group
        )
        await app.push_screen(Screen())
        await ui.until(
            lambda: all(worker.is_finished for worker in workers),
            seconds=12,
            why="the load to run its course under the covering screen",
        )
        app.pop_screen()
        async with asyncio.timeout(12):
            await sidebar.wait_content_ready()
        await ui.step(0.02)
        assert sidebar.panels_loaded
        assert len(sidebar.panels) == len(sidebar._panel_owners)
        assert tuple(sidebar.layout_controls.children)
        assert not sidebar.present_controls(), "its controls were never presented for its placement"


async def test_a_sidebar_asked_to_load_under_an_opaque_screen_loads_once_uncovered(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=ToadApp) as ui:
        app, _ = ui.textual
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        await sidebar.evict(screen)
        await app.push_screen(Screen())
        await sidebar.prepare_presentation()
        await ui.step(0.05)
        assert not sidebar.panels
        app.pop_screen()
        await ui.step(0.05)
        async with asyncio.timeout(12):
            await sidebar.wait_content_ready()
        assert sidebar.panels_loaded
        assert tuple(sidebar.layout_controls.children)
