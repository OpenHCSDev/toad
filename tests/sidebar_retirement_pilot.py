"""Installed rich-panel owner: real filesystem, relationship service and teardown.

This checks the public sidebar lifetime independently. The 64-tab companion
requires the ordinary MainScreen caller rather than supplying a test owner.
"""
import asyncio
import gc
from importlib.resources import files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from weakref import ref

from agent_comms.comms import wire
from agent_comms.threads import Thread
from runtime_fixture import ToadApp
from toad.plan import PlanItem, PendingPlanStatus, InProgressPlanStatus
from toad.widgets.plan import Plan
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible
from toad.widgets.sidebar_viewport import SidebarViewport
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.screens.main import MainScreen
from textual.content import Content


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


async def until(pilot, condition):
    async with asyncio.timeout(12):
        while not condition():
            await pilot.pause(.02)


async def reveal(screen, pilot):
    sidebar = screen.query_one(SessionThreadSidebar)
    sidebar.reveal()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await pilot.pause(.02)
    return sidebar


async def prepare_project(sidebar, pilot):
    sidebar.query_one("#project-panel", SideBarCollapsible).collapsed = False
    await until(pilot, lambda: sidebar.query_one_optional(ProjectDirectoryTree) is not None)
    tree = sidebar.query_one(ProjectDirectoryTree)
    await until(pilot, lambda: tree.path_filter is not None and not tree._load_queue._unfinished_tasks)
    await pilot.pause(.02)
    return tree


def viewport_text(widget):
    """Crop actual compositor strips to the visible native widget viewport."""
    region, clip = widget.screen.screen._compositor.visible_widgets[widget]
    region = region.intersection(clip).intersection(widget.screen.region)
    return "\n".join(strip.crop(region.x, region.right).text
                     for strip in widget.screen.screen._compositor.render_strips()[region.y:region.bottom])


async def exercise(screen, pilot, root):
    sidebar = await reveal(screen, pilot)
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await until(pilot, lambda: len(relationships.groups) == 5)
    group = relationships.groups["collaborating"]
    if not group.expanded:
        group.toggle_members()
    await until(pilot, lambda: bool(group.rows))
    row = next(iter(group.rows.values()))
    relationships.remember_row(row)
    if group.expanded:
        group.toggle_members()
    await pilot.pause(.02)
    tree = await prepare_project(sidebar, pilot)
    folder = next(node for node in tree.root.children if node.data.path == root / "folder")
    folder.expand()
    await tree._add_to_load_queue(folder)
    deep = next(node for node in folder.children if node.data.path == root / "folder/deep")
    deep.expand()
    await tree._add_to_load_queue(deep)
    selected = next(node for node in deep.children if node.data.path.name == "item-38.txt")
    tree.move_cursor(selected, animate=False)
    tree.scroll_to(y=12, animate=False, immediate=True)
    viewport = sidebar.query_one("#sidebar-panels", SidebarViewport)
    viewport.scroll_to(y=3, animate=False, immediate=True)
    await pilot.pause(.02)
    state = relationships.view_state
    tree_scroll, panel_scroll = tree.scroll_y, viewport.scroll_y
    assert state.selected == ("collaborating", "peer")
    saved = [ref(panel.widget) for panel in sidebar.panels]
    tree_ref = ref(tree)
    await sidebar.retire_presentation()
    assert not sidebar.panels and not sidebar._panels_loaded
    assert screen._project_panel is None
    assert not tuple(viewport.children)
    assert not sidebar.query(Plan) and not sidebar.query(ThreadCommsSidebar)
    del relationships, tree, row, group, selected, folder, deep
    await pilot.pause(.05)
    gc.collect()
    assert all(widget() is None for widget in saved), "Retired panel graph remains reachable"
    assert tree_ref() is None, "Retired DirectoryTree remains reachable"
    latest = [PlanItem(Content("Latest while absent"), "high", InProgressPlanStatus)]
    sidebar.update_plan(latest)
    await sidebar.prepare_presentation()
    async with asyncio.timeout(12):
        await sidebar.wait_content_ready()
    await pilot.pause(.02)
    assert sidebar.query_one(Plan).entries is latest
    relationships = sidebar.query_one(ThreadCommsSidebar)
    await until(pilot, lambda: len(relationships.groups) == 5)
    assert relationships.view_state is state
    assert state.selected == ("collaborating", "peer")
    assert not relationships.groups["collaborating"].expanded
    tree = await prepare_project(sidebar, pilot)
    await until(pilot, lambda: tree.cursor_node is not None and tree.cursor_node.data.path == root / "folder/deep/item-38.txt")
    await pilot.pause(.05)
    assert tree.scroll_y == tree_scroll, (tree.scroll_y, tree_scroll, tree.size, tree.virtual_size)
    assert viewport.scroll_y == panel_scroll, (viewport.scroll_y, panel_scroll)
    assert all(word in viewport_text(sidebar) for word in ("Latest", "while", "absent"))
    tree.scroll_visible(animate=False, immediate=True)
    tree.scroll_to(y=tree.max_scroll_y, animate=False, immediate=True)
    await pilot.pause(.02)
    assert "item-38.txt" in viewport_text(tree), ("Restored filename was not actually painted", viewport_text(tree))
    print(json.dumps({"restored_selection": str(tree.cursor_node.data.path), "tree_scroll": tree_scroll,
                      "panel_scroll": panel_scroll, "retired_widgets_collected": len(saved)+1}), flush=True)


async def main():
    with TemporaryDirectory(prefix="sidebar-retirement-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        project = root / "project"
        (project / "folder/deep").mkdir(parents=True)
        for index in range(48):
            (project / "folder/deep" / f"item-{index:02}.txt").write_text(str(index))
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        for name in ("owner", "peer"):
            comms.threads.register(Thread(name, frozenset(), str(project)))
        comms.relationships.edit("owner", "add", "peer", "Actual relationship")
        app = InstalledApp(project_dir=str(project))
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause(.02)
            screen = app.selected_session
            screen._comms_thread = "owner"
            screen.initial_coordination_root = str(root / "wire")
            for _ in range(3):
                await exercise(screen, pilot, project)
            sidebar = screen.query_one(SessionThreadSidebar)
            await sidebar.retire_presentation()
            sidebar.reveal()
            sidebar.collapsed = True
            await pilot.pause(.05)
            assert not sidebar.panels
            sidebar.reveal()
            await sidebar.wait_content_ready()
            assert len(sidebar.panels) == 5
            # Change the source project while the optional presentation is gone.
            await sidebar.retire_presentation()
            replacement = root / "replacement-project"
            replacement.mkdir()
            (replacement / "new-source.txt").write_text("Current filesystem")
            screen.project_path = replacement
            await sidebar.prepare_presentation()
            await sidebar.wait_content_ready()
            tree = await prepare_project(sidebar, pilot)
            assert Path(tree.path) == replacement
            assert not any(node.data.path.name == "folder" for node in tree.root.children)
            tree.scroll_visible(animate=False, immediate=True)
            await pilot.pause(.02)
            assert "new-source.txt" in viewport_text(tree)
            del tree
            # Enter the real hydration worker, then switch through the normal
            # production caller before its mount finishes. No gated/mock mount.
            await sidebar.retire_presentation()
            sidebar._start_hydration()
            assert sidebar._panels_loading
            workers = tuple(worker for worker in sidebar.workers
                            if worker.node is sidebar and worker.group == "sidebar-panels")
            await asyncio.sleep(0)
            await app.new_session_screen(lambda: MainScreen(replacement))
            await pilot.pause(.02)
            assert not sidebar.panels and not sidebar._panels_loading
            assert all(worker.is_finished for worker in workers)
            await app.select_session(screen.id)
            await sidebar.wait_content_ready()
            assert len(sidebar.panels) == 5
            assert app._exception is None
    print("PASS: installed sidebar public lifetime, repeated real state restoration and rich graph collection", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
