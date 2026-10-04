"""Test-owned daemons need explicit teardown; closing a UI deliberately leaves them running."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import psutil
from agent_comms.comms import wire
from agent_comms.child_process import STOP_GRACE_SECONDS
from agent_comms.active_route import resolve_comms_route
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
    runner = psutil.Process()
    ancestors = {process.pid for process in runner.parents()}
    for process in psutil.process_iter():
        try:
            if (process.pid != runner.pid and process.pid not in ancestors
                    and process.environ().get("TOAD_TEST_ATTEMPT") == attempt):
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


@asynccontextmanager
async def _cleanup_on_exit(callback, *args):
    try:
        yield
    finally:
        await callback(*args)


class ToadApp(Application):
    CSS_PATH = Path(__file__).resolve().parents[1] / "src/toad/toad.tcss"

    @asynccontextmanager
    async def run_test(self, **kwargs):
        root = resolve_comms_route().observe_root()
        async with AsyncExitStack() as cleanup:
            await cleanup.enter_async_context(_cleanup_on_exit(asyncio.to_thread, _clear_wire_locks, root))
            await cleanup.enter_async_context(_cleanup_on_exit(stop_test_children, os.environ.get("TOAD_TEST_ATTEMPT")))
            await cleanup.enter_async_context(_cleanup_on_exit(asyncio.to_thread, stop_test_owners, root))
            async with super().run_test(**kwargs) as pilot:
                yield pilot


async def refresh_comms(view):
    """Explicit test completion borrows the original pager's worker resource.

    The production callback only schedules I/O; receipt/input handlers must
    remain free to process events while this read is outstanding.
    """
    worker = await view._refresh()
    if worker is not None:
        await worker.wait()


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
            if (sidebar.navigation.ready.is_set() and sidebar.display
                    and not sidebar.observation.pending
                    and not sidebar.observation.lock.locked() and not sidebar.projection.lock.locked()
                    and set(targets) <= {row.target_name for row in sidebar.projection.channels.values()}):
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


async def wait_fork_dialog(app, pilot, *, seconds=20):
    """Await the original mounted, focused and physically hittable dialog."""
    from textual.widgets import Input
    from toad.widgets.comms_command_dialog import CommandDialog

    async with asyncio.timeout(seconds):
        while True:
            dialog = app.screen
            if isinstance(dialog, CommandDialog) and dialog.is_mounted and dialog.is_attached:
                entry = dialog.query_one_optional('#command-field-name', Input)
                if (entry is not None and entry.is_mounted and entry.is_attached
                        and dialog.focused is entry and app.focused is entry
                        and entry.region.width > 0 and entry.region.height > 0
                        and entry.region.offset in dialog.size.region
                        and dialog.get_widget_at(*entry.region.offset)[0] is entry):
                    return dialog
            await pilot.pause(.02)


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


def request_target(app, command, subject):
    """Existing native control fixtures borrow the backend declaration query."""
    from agent_comms.cli_commands import CliCommand, TargetEdit
    from toad.thread_actions import ThreadAction
    comms = app.coordination_access.service
    definition = next(item for item in CliCommand.target_catalog(
        comms, subject, project=str(app.project_dir))
        if item.declaration is command)
    app.thread_actions.invoke(ThreadAction(definition, TargetEdit(
        target=subject, declaration=command, arguments={})), subject)


def retain_fixture_journals(paths, *, stage: Path, evidence: Path,
                           cold_mount: Path = Path("/run/media/ts/hdd")) -> None:
    """Cold-retain exact owned SDK copies after terminal keeper publication.

    This does not dispose source history or change SessionManager. The existing
    privileged borrower census must clear every supplied leaf before storage
    moves; the caller and its ancestors are the already-closed fixture lease.
    """
    paths = tuple(Path(path).absolute() for path in paths)
    for path in paths:
        path.relative_to(stage / "native-forks" / "sessions")
        if path.suffix != ".jsonl" or not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError(f"Not an original owned fixture journal: {path}")
    candidates = evidence / "journal-retention-candidates.json"
    candidates.write_text(json.dumps({"items": [{"path": str(p)} for p in paths]}, indent=2) + "\n")
    census = evidence / "journal-retention-borrowers.json"
    checker = Path("/home/ts/.cache/agent-scratch/disk-cleanup-owner-20261002/borrower-census.py")
    receipt = {"borrower_census": str(census), "files": []}
    retained = evidence / "journal-retention.json"
    try:
        if not cold_mount.is_mount():
            raise OSError(f"Cold storage is not mounted: {cold_mount}")
        cold_device = cold_mount.stat().st_dev
        if any(path.stat().st_dev == cold_device for path in paths):
            raise OSError("Cold storage must differ from the source filesystem")
        if not checker.is_file():
            raise FileNotFoundError(checker)
        subprocess.run(("sudo", "-n", sys.executable, str(checker), str(candidates), str(census)),
                       check=True, stdout=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as error:
        receipt["retained_reason"] = str(error)
        retained.write_text(json.dumps(receipt, indent=2) + "\n")
        return
    borrowers = json.loads(census.read_text())
    retained.write_text(json.dumps(receipt, indent=2) + "\n")
    if borrowers["gaps"] or any(borrowers["refs"][str(path)] for path in paths):
        receipt["retained_reason"] = "Borrowers or census permission gaps remain"
        retained.write_text(json.dumps(receipt, indent=2) + "\n")
        return  # Original leaves remain intact while actual custody is open.
    cold_root = cold_mount / "agent-comms-retained" / "history-sdk-fixture"
    for path in paths:
        before = path.stat()
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        destination = cold_root / path.relative_to(path.anchor)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.stat().st_dev != cold_device:
            raise OSError("Cold destination escaped the mounted filesystem")
        if destination.exists():
            raise FileExistsError(destination)
        partial = destination.with_name(destination.name + ".partial")
        with path.open("rb") as source, partial.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fchmod(target.fileno(), stat.S_IMODE(before.st_mode))
            os.fsync(target.fileno())
        with partial.open("rb") as target:
            if hashlib.file_digest(target, "sha256").hexdigest() != digest:
                raise RuntimeError(f"Copied fixture journal differs: {path}")
        current = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns):
            raise RuntimeError(f"Original fixture journal changed: {path}")
        record = {"path": str(path), "destination": str(destination), "sha256": digest,
                  "original_dev": before.st_dev, "original_inode": before.st_ino,
                  "bytes": before.st_size, "mtime_ns": before.st_mtime_ns,
                  "mode": before.st_mode}
        receipt["files"].append(record)
        retained.write_text(json.dumps(receipt, indent=2) + "\n")
        partial.rename(destination)
        _sync_fixture_directory(destination.parent)
        link = path.with_name(path.name + ".cold-link")
        link.symlink_to(destination)
        if (not cold_mount.is_mount() or cold_mount.stat().st_dev != cold_device
                or destination.stat().st_dev != cold_device):
            receipt["retained_reason"] = "Cold mount changed before source replacement"
            retained.write_text(json.dumps(receipt, indent=2) + "\n")
            link.unlink()
            return
        os.replace(link, path)
        _sync_fixture_directory(path.parent)
        with path.open("rb") as original_path:
            if hashlib.file_digest(original_path, "sha256").hexdigest() != digest:
                raise RuntimeError(f"Retained fixture path differs: {path}")
        record["verified_through_original_path"] = True
        retained.write_text(json.dumps(receipt, indent=2) + "\n")


def _sync_fixture_directory(directory: Path) -> None:
    """Persist a resource rename before retiring its preceding location."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
