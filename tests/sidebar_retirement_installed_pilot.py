"""Ordinary installed 64-tab reveal/return through workspace admission hooks.

No patched MainScreen, test switch owner, mocked source or paid provider call.
"""
import asyncio
import gc
import inspect
import json
import os
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
import time
from weakref import ref

import psutil
from agent_comms.comms import wire
from agent_comms.threads import Thread
from sidebar_retirement_pilot import InstalledApp, until, reveal, prepare_project, viewport_text
from toad.screens.main import MainScreen
from toad.plan import PlanItem, PendingPlanStatus, InProgressPlanStatus
from toad.widgets.plan import Plan
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.side_bar import SideBarCollapsible
from toad.widgets.thread_comms import ThreadCommsSidebar
from textual.content import Content


def rich_count(screens):
    return sum(len(screen.query_one(SessionThreadSidebar).panels) for screen in screens)


async def main():
    for method in (MainScreen.prepare_presentation, MainScreen.retire_presentation):
        source = inspect.getsource(method)
        assert "SessionThreadSidebar" in source, f"Missing production caller: {method.__qualname__}"
    with TemporaryDirectory(prefix="sidebar-scale-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        project = root / "project"
        (project / "folder/deep").mkdir(parents=True)
        for index in range(48):
            (project / "folder/deep" / f"item-{index:02}.txt").write_text(str(index))
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        comms = wire(root / "wire")
        tabs = int(os.environ.get("TOAD_SIDEBAR_TABS", "64"))
        for name in ["peer"] + [f"owner-{index}" for index in range(tabs)]:
            comms.threads.register(Thread(name, frozenset(), str(project)))
        comms.relationships.edit("owner-0", "add", "peer", "Persist actual relationship state")
        app = InstalledApp(project_dir=str(project))
        measurements, timings, screens, references = [], [], [], []
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause(.02)
            first = app.selected_session
            first._comms_thread = "owner-0"
            first.initial_coordination_root = str(root / "wire")
            screens.append(first)
            first_bar = await reveal(first, pilot)
            tree = await prepare_project(first_bar, pilot)
            folder = next(node for node in tree.root.children if node.data.path.name == "folder")
            folder.expand()
            await tree._add_to_load_queue(folder)
            deep = next(node for node in folder.children if node.data.path.name == "deep")
            deep.expand()
            await tree._add_to_load_queue(deep)
            selected = next(node for node in deep.children if node.data.path.name == "item-38.txt")
            tree.move_cursor(selected, animate=False)
            tree.scroll_to(y=12, animate=False, immediate=True)
            await pilot.pause(.02)
            tree_scroll = tree.scroll_y
            relationships = first_bar.query_one(ThreadCommsSidebar)
            await until(pilot, lambda: len(relationships.groups) == 5)
            group = relationships.groups["collaborating"]
            row = next(iter(group.rows.values()))
            relationships.remember_row(row)
            group.toggle_members()
            await pilot.pause(.02)
            state = relationships.view_state
            references.extend(ref(panel.widget) for panel in first_bar.panels)
            references.append(ref(tree))
            del tree, selected, folder, deep, relationships, group, row
            for index in range(1, tabs):
                def make_screen(index=index):
                    screen = MainScreen(project)
                    screen._comms_thread = f"owner-{index}"
                    screen.initial_coordination_root = str(root / "wire")
                    return screen
                await app.new_session_screen(make_screen)
                screen = app.selected_session
                screens.append(screen)
                await pilot.pause(.02)
                bar = await reveal(screen, pilot)
                bar.update_plan([PlanItem(Content(f"Plan {index}"), "high", PendingPlanStatus)])
                assert len(bar.panels) == 5
                assert rich_count(screens) == 5, f"Retained rich panels after {len(screens)} tabs"
                references.extend(ref(panel.widget) for panel in bar.panels)
                if len(screens) in {4, 16, 32, 64}:
                    gc.collect()
                    measurements.append({"tabs": len(screens), "rich_panels": rich_count(screens),
                                         "rss_bytes": psutil.Process().memory_info().rss,
                                         "tasks": len(asyncio.all_tasks())})
            assert not first_bar.panels
            latest = [PlanItem(Content("Source update while inactive"), "high", InProgressPlanStatus)]
            first_bar.update_plan(latest)
            for screen in reversed(screens):
                started = time.perf_counter()
                await app.select_session(screen.id)
                await pilot.pause(.02)
                bar = screen.query_one(SessionThreadSidebar)
                await bar.wait_content_ready()
                timings.append((time.perf_counter() - started) * 1000)
                assert len(bar.panels) == rich_count(screens) == 5
                if screen is first:
                    assert bar.query_one(Plan).entries is latest
                    tree = await prepare_project(bar, pilot)
                    await until(pilot, lambda: tree.cursor_node is not None and tree.cursor_node.data.path == project / "folder/deep/item-38.txt")
                    await pilot.pause(.02)
                    assert tree.scroll_y == tree_scroll, (tree.scroll_y, tree_scroll,
                        tree.size, tree.virtual_size, tree.max_scroll_y, tree.cursor_line)
                    relationships = bar.query_one(ThreadCommsSidebar)
                    assert relationships.view_state is state
                    assert state.selected == ("collaborating", "peer")
                    assert "Source" in viewport_text(bar) and "inactive" in viewport_text(bar)
                    tree.scroll_visible(animate=False, immediate=True)
                    tree.scroll_to(y=tree.max_scroll_y, animate=False, immediate=True)
                    await pilot.pause(.02)
                    assert "item-38.txt" in viewport_text(tree), "Restored selected filename not painted"
                    relationships.scroll_visible(animate=False, immediate=True)
                    await pilot.pause(.02)
                    await until(pilot, lambda: len(relationships.groups) == 5)
                    assert not relationships.groups["collaborating"].expanded
                    relationships.groups["collaborating"].toggle_members()
                    await until(pilot, lambda: bool(relationships.groups["collaborating"].rows))
                    await pilot.pause(.02)
                    assert "peer" in viewport_text(relationships), "Restored relationship not painted"
                    assert next(iter(relationships.groups["collaborating"].rows.values())).has_class("-selected")
                    app.save_screenshot("sidebar-return.svg", path="evidence/sidebar-retirement")
                    del tree, relationships
                else:
                    assert bar.query_one(Plan).entries[0].content.plain == f"Plan {screens.index(screen)}"
                    assert f"Plan {screens.index(screen)}" in viewport_text(bar), "Plan text not painted on return"
                if screen is screens[tabs // 2]:
                    await pilot.resize_terminal(106, 37)
                    await pilot.pause(.02)
            await pilot.pause(.05)
            gc.collect()
            assert all(widget() is None for widget in references), "A retired graph remains reachable"
            assert app._exception is None
        receipt = {"cohorts": measurements, "returns": len(timings),
                   "settled_return_median_ms": median(timings), "settled_return_max_ms": max(timings),
                   "collected_retired_widgets": len(references),
                   "boundary": "actual installed MainScreen/App selection hooks, filesystem and relationship service; no ACP provider claimed"}
        target = Path(os.environ.get("TOAD_SIDEBAR_RECEIPT", Path.cwd() / "evidence/sidebar-retirement/scale-receipt.json"))
        target.write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
