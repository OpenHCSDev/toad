"""Test-owned daemons need explicit teardown; closing a UI deliberately leaves them running."""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path

import psutil
from agent_comms import wire
from toad.app import ToadApp as Application


def stop_test_owners(root: Path) -> None:
    comms = wire(root)
    for thread in comms.registry.all_threads().values():
        if thread.pid <= 0:
            continue
        try:
            process = psutil.Process(thread.pid)
            if "agent_comms.worker" not in process.cmdline():
                continue
            if Path(process.environ().get("AGENT_COMMS_ROOT", "")).resolve() != root.resolve():
                continue
            comms.stop(thread.name)
            process.wait(timeout=10)
        except psutil.NoSuchProcess:
            pass


class ToadApp(Application):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"

    @asynccontextmanager
    async def run_test(self, **kwargs):
        root = Path(os.environ["AGENT_COMMS_ROOT"])
        try:
            async with super().run_test(**kwargs) as pilot:
                yield pilot
        finally:
            await asyncio.to_thread(stop_test_owners, root)
            await asyncio.to_thread(_clear_wire_locks, root)


def _clear_wire_locks(root: Path) -> None:
    """Remove stale per-file store locks so TemporaryDirectory cleanup succeeds.

    Lock files are created with O_EXCL next to the store they guard; a live
    in-process wire can hold them when the app exits before its workers flush.
    """
    wire_dir = Path(root) / "wire"
    if wire_dir.is_dir():
        for lock in wire_dir.glob(".*.lock"):
            try:
                lock.unlink()
            except OSError:
                pass


async def reveal_project_tree(app, pilot):
    """Open the thread-local Project panel; trees are intentionally lazy now."""
    from toad.widgets.side_bar import SideBar, SideBarCollapsible
    from toad.widgets.project_directory_tree import ProjectDirectoryTree

    sidebar = app.screen.query_one("#thread-sidebar", SideBar)
    sidebar.reveal()
    next(panel for panel in sidebar.query(SideBarCollapsible) if panel.title == "Project").collapsed = False
    async with asyncio.timeout(5):
        while True:
            tree = sidebar.query_one_optional(ProjectDirectoryTree)
            if tree is not None and tree.path_filter is not None:
                await pilot.pause()
                return tree
            await pilot.pause(.05)
