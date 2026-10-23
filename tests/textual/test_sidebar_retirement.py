"""Textual-facing: a thread sidebar's optional panels are released and rebuilt with their selection, scroll and plan state, and the rich widget graph is collected."""

import asyncio
import gc
from weakref import ref

from agent_comms.relationships import AddRelationshipEdit, CollaboratingRelationshipGroup

from support.stylesheets import INSTALLED
from toad.app import ToadApp
from toad.plan import InProgressPlanStatus, PlanItem
from toad.screens.main import MainScreen
from toad.widgets.plan import Plan
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar
from support.ui import saved_tab


class InstalledApp(ToadApp):
    CSS_PATH = INSTALLED


def viewport_text(widget):
    """Crop actual compositor strips to the visible native widget viewport."""
    region, clip = widget.screen.screen._compositor.visible_widgets[widget]
    region = region.intersection(clip).intersection(widget.screen.region)
    return "\n".join(strip.crop(region.x, region.right).text
                     for strip in widget.screen.screen._compositor.render_strips()[region.y:region.bottom])


def project_with_files(workspace):
    (workspace.project / "folder/deep").mkdir(parents=True)
    for index in range(48):
        (workspace.project / "folder/deep" / f"item-{index:02}.txt").write_text(str(index))
    for name in ("owner", "peer"):
        workspace.thread(name)
    workspace.comms.relationships.edit("owner", AddRelationshipEdit, "peer", "Actual relationship")


async def started(workspace, ui):
    screen = ui.app.selected_session
    await workspace.bind(screen, "owner")
    return screen


async def reveal(ui, screen):
    sidebar = screen.query_one(SessionThreadSidebar)
    sidebar.reveal()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await ui.step(.02)
    return sidebar


async def prepare_project(ui, sidebar):
    sidebar.query_one("#project-panel", SideBarCollapsible).collapsed = False
    await ui.until(lambda: sidebar.query_one_optional(ProjectDirectoryTree) is not None, seconds=12, why="the project tree")
    tree = sidebar.query_one(ProjectDirectoryTree)
    await ui.until(lambda: tree.path_filter is not None and not tree._load_queue._unfinished_tasks,
                   seconds=12, why="the project tree to load")
    await ui.step(.02)
    return tree


async def exercise(ui, screen, root):
    sidebar = await reveal(ui, screen)
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await ui.until(lambda: CollaboratingRelationshipGroup in relationships.groups, seconds=12, why="the collaborating group")
    group = relationships.groups[CollaboratingRelationshipGroup]
    if not group.expanded:
        group.toggle_members()
    await ui.until(lambda: bool(group.rows), seconds=12, why="the collaborating rows")
    row = next(iter(group.rows.values()))
    relationships.remember_row(row)
    chosen = relationships.selection_for(row)
    assert chosen[0] is CollaboratingRelationshipGroup and row.entry.target == "peer"
    if group.expanded:
        group.toggle_members()
    await ui.step(.02)
    tree = await prepare_project(ui, sidebar)
    folder = next(node for node in tree.root.children if node.data.path == root / "folder")
    folder.expand()
    await tree._add_to_load_queue(folder)
    deep = next(node for node in folder.children if node.data.path == root / "folder/deep")
    deep.expand()
    await tree._add_to_load_queue(deep)
    selected = next(node for node in deep.children if node.data.path.name == "item-38.txt")
    tree.move_cursor(selected, animate=False)
    tree.scroll_to(y=12, animate=False, immediate=True)
    viewport = sidebar.panels_viewport
    viewport.scroll_to(y=3, animate=False, immediate=True)
    await ui.step(.02)
    state = relationships.view_state
    tree_scroll, panel_scroll = tree.scroll_y, viewport.scroll_y
    assert state.selected == chosen
    saved = [ref(panel.widget) for panel in sidebar.panels]
    tree_ref = ref(tree)
    await sidebar.retire_presentation()
    assert all(widget() is panel.widget for widget, panel in zip(saved, sidebar.panels, strict=True))
    assert tree_ref() is sidebar.query_one(ProjectDirectoryTree)
    await sidebar.prepare_presentation()
    assert tree_ref() is sidebar.query_one(ProjectDirectoryTree)
    await sidebar.evict()
    assert not sidebar.panels and not sidebar._panels_loaded
    assert screen._project_panel is None
    assert not tuple(viewport.children)
    assert not sidebar.query(Plan) and not sidebar.query(ThreadCommsSidebar)
    del relationships, tree, row, group, selected, folder, deep
    await ui.step(.05)
    gc.collect()
    assert all(widget() is None for widget in saved), "Retired panel graph remains reachable"
    assert tree_ref() is None, "Retired DirectoryTree remains reachable"
    latest = [PlanItem("Latest while absent", "high", InProgressPlanStatus)]
    sidebar.update_plan(latest)
    await sidebar.prepare_presentation()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await ui.step(.02)
    assert sidebar.query_one(Plan).entries is latest
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await ui.until(lambda: CollaboratingRelationshipGroup in relationships.groups, seconds=12, why="the collaborating group after rebuild")
    assert relationships.view_state is state
    assert state.selected == chosen
    assert not relationships.groups[CollaboratingRelationshipGroup].expanded
    tree = await prepare_project(ui, sidebar)
    await ui.until(lambda: tree.cursor_node is not None and tree.cursor_node.data.path == root / "folder/deep/item-38.txt",
                   seconds=12, why="the project tree cursor to be restored")
    await ui.until(lambda: screen._project_panel._intent is None, seconds=12, why="the project panel to settle")
    assert tree.scroll_y == tree_scroll, (tree.scroll_y, tree_scroll, tree.size, tree.virtual_size)
    assert viewport.scroll_y == panel_scroll, (viewport.scroll_y, panel_scroll)
    assert all(word in viewport_text(sidebar) for word in ("Latest", "while", "absent"))
    tree.scroll_visible(animate=False, immediate=True)
    tree.scroll_to(y=tree.max_scroll_y, animate=False, immediate=True, force=True)
    await ui.step(.02)
    assert "item-38.txt" in viewport_text(tree), ("Restored filename was not actually painted", viewport_text(tree))


async def test_panels_restore_selection_scroll_and_plan_after_release_and_collect_the_old_widgets(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=InstalledApp) as ui:
        screen = await started(workspace, ui)
        for _ in range(3):
            await exercise(ui, screen, workspace.project)


async def test_panels_rebuild_after_eviction_while_collapsed(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=InstalledApp) as ui:
        screen = await started(workspace, ui)
        sidebar = screen.query_one(SessionThreadSidebar)
        await sidebar.evict()
        sidebar.reveal()
        sidebar.collapsed = True
        await ui.step(.05)
        assert not sidebar.panels
        sidebar.reveal()
        await sidebar.wait_content_ready()
        assert len(sidebar.panels) == len(sidebar._panel_owners)


async def test_panels_show_the_current_project_after_the_source_project_changes_while_released(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=InstalledApp) as ui:
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        await sidebar.evict()
        replacement = workspace.project.parent / "replacement-project"
        replacement.mkdir()
        (replacement / "new-source.txt").write_text("Current filesystem")
        screen.project_path = replacement
        await sidebar.prepare_presentation()
        await sidebar.wait_content_ready()
        tree = await prepare_project(ui, sidebar)
        assert tree.path == replacement or str(tree.path) == str(replacement)
        assert not any(node.data.path.name == "folder" for node in tree.root.children)
        tree.scroll_visible(animate=False, immediate=True)
        await ui.step(.02)
        assert "new-source.txt" in viewport_text(tree)


async def test_leaving_a_view_stops_its_sidebar_hydration(workspace):
    project_with_files(workspace)
    async with workspace.app(size=(130, 44), application=InstalledApp) as ui:
        app, _ = ui.textual
        screen = await started(workspace, ui)
        sidebar = await reveal(ui, screen)
        # The next tab is saved first, so leaving the view does not wait on the database.
        tab = await saved_tab(app)
        await sidebar.evict()
        sidebar._start_hydration()
        assert sidebar._panels_loading
        workers = tuple(worker for worker in sidebar.workers
                        if worker.node is sidebar and worker.group == "sidebar-panels")
        await asyncio.sleep(0)
        await app.session_navigation.new(tab, lambda: MainScreen(workspace.project))
        await ui.step(.02)
        assert not sidebar.panels and not sidebar._panels_loading
        assert all(worker.is_finished for worker in workers)
        await app.select_session(screen.id)
        await sidebar.wait_content_ready()
        assert len(sidebar.panels) == len(sidebar._panel_owners)
