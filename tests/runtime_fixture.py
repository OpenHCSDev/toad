"""Test-owned daemons need explicit teardown; closing a UI deliberately leaves them running."""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path

import psutil
from agent_comms.comms import wire
from agent_comms.child_process import STOP_GRACE_SECONDS
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
            comms.owners.stop(thread.name)
            process.wait(timeout=10)
        except psutil.NoSuchProcess:
            pass


async def stop_test_children(attempt: str | None) -> None:
    """Retire only children carrying this runner's private attempt attestation."""
    if attempt is None:
        return
    for process in psutil.process_iter():
        try:
            if process.pid != os.getpid() and process.environ().get("TOAD_TEST_ATTEMPT") == attempt:
                # xclip is an external daemon, not a ChildProcess session leader.
                # psutil guards PID reuse; zombies have already closed their pipes.
                process.terminate()
                try:
                    async with asyncio.timeout(STOP_GRACE_SECONDS):
                        while process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                            await asyncio.sleep(.02)
                except TimeoutError:
                    process.kill()
                    async with asyncio.timeout(STOP_GRACE_SECONDS):
                        while process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                            await asyncio.sleep(.02)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            continue


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
            await stop_test_children(os.environ.get("TOAD_TEST_ATTEMPT"))
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
    await sidebar.wait_content_ready()
    next(panel for panel in sidebar.query(SideBarCollapsible) if panel.title == "Project").collapsed = False
    async with asyncio.timeout(5):
        while True:
            tree = sidebar.query_one_optional(ProjectDirectoryTree)
            if tree is not None and tree.path_filter is not None:
                await pilot.pause()
                return tree
            await pilot.pause(.05)


async def wait_channel_roster(app, pilot, *targets):
    """Wait for the first-frame asynchronous roster, not merely an idle queue."""
    from toad.widgets.comms_sidebar import CommsSidebar

    async with asyncio.timeout(8):
        while True:
            sidebar = app.screen.query_one(CommsSidebar)
            if (sidebar.navigation_ready.is_set() and sidebar.display
                    and not sidebar._snapshot_pending
                    and not sidebar._snapshot_lock.locked() and not sidebar._presentation_lock.locked()
                    and set(targets) <= {row.target_name for row in sidebar._row_map.values()}):
                return sidebar
            await pilot.pause(.02)


async def reveal_session_details(app, pilot, target=None):
    """Use the native disclosure before inspecting normally collapsed metadata."""
    from toad.widgets.session_details import SessionDetails

    details = app.screen.query_one(SessionDetails)
    if details.collapsed:
        assert await pilot.click(details.query_one("CollapsibleTitle"))
        await pilot.pause()
    if target is not None:
        target.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
    return details


def private_native_wire(root: Path):
    """Declare the real current native route on a disposable test-owned wire."""
    from agent_comms.native_package import verify_native_package
    package = Path(os.environ["AC_NATIVE_COPIED_PACKAGE"])
    verify_native_package(package)
    comms = wire(root)
    root_id = comms.messaging.initialize_private_initial_protocol()
    os.environ.update(
        AGENT_COMMS_ROOT=str(root),
        AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=root_id,
        AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=str(package),
    )
    return comms


def coordination_update(root, name):
    """Stimulate the UI with current metadata derived from its real fixture registry."""
    from agent_comms.acp_extension import CoordinationChangedUpdate
    from agent_comms.comms import wire
    thread = wire(Path(root)).registry.require(name)
    return CoordinationChangedUpdate(thread.incarnation, str(root), thread.pid,
        thread.worktree or "", thread.model, thread.thinking_level,
        thread.title or thread.name, None)
