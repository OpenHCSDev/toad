"""Count original native page admissions without a provider or public root.

Exercises committed rows while original native Mount/Unmount is pending.
Imports must resolve to the installed package; no source overlay is permitted.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from importlib import metadata

from agent_comms.comms import Comms
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.threads import Thread
from textual import events
from textual.geometry import Size
from toad.app import ToadApp
from toad.widgets.comms_chat import session_thread_name
from toad.widgets.transcript_history import (
    TranscriptHistory, TranscriptPageView, TranscriptFragmentView, ProjectedTranscriptHistory,
)
from toad.transcript_filter import Filtered
from toad.transcript_state import LatestViewportRequest


class PendingFragment(TranscriptFragmentView):
    """Hold actual native events; source admission and pruning stay production."""

    def __init__(self, *args, mount=None, unmount=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mount_receipt, self.unmount_receipt = mount, unmount

    async def on_mount(self):
        if self.mount_receipt is not None:
            entered, release = self.mount_receipt
            entered.set()
            await release.wait()

    async def on_unmount(self):
        if self.unmount_receipt is not None:
            entered, release, finished = self.unmount_receipt
            entered.set()
            try:
                await release.wait()
            finally:
                finished.set()


class PendingPage(TranscriptPageView):
    """Use the original page algorithm with a real leaf event boundary."""

    mount_receipt = None

    async def on_mount(self):
        if self.mount_receipt is not None:
            entered, release = self.mount_receipt
            entered.set()
            await release.wait()

    def _body(self, fragment):
        return PendingFragment(fragment, self.visible_categories)


async def main(output):
    output.mkdir(parents=True, exist_ok=False)
    package = Path(metadata.distribution("batrachian-toad").locate_file("toad")).resolve()
    import toad
    assert Path(toad.__file__).resolve().parent == package
    assert package.is_relative_to(Path(sys.prefix).resolve()), "Driver imported a source overlay"
    checks = {}
    tasks, releases = [], []
    with TemporaryDirectory(dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        service = Comms(root / "wire")
        service.messaging.initialize_private_initial_protocol()
        service.registry.declare(Thread(session_thread_name(root), frozenset(), str(root)))
        source = str(root / "saved-source")
        page = TranscriptPage(tuple(AssistantTranscript(
            f"## Original record {index}\n\nNative ordered admission paragraph.",
        ) for index in range(32)), TranscriptCursor(source, 0),
            TranscriptCursor(source, 32), False, False)

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            await view.window.document_viewport.suspend_source()
            history = TranscriptHistory(page, committed=False)
            history.pages[0] = PendingPage(page)
            operation = None
            try:
                await view.post(history)
                checks["provisional_source_blocks_visible_read"] = history.blocks_visible_read
                history.publish_committed()
                operation = history.reserve_source_work()
                checks["admitted_work_blocks_visible_read"] = (
                    history.state is operation and history.blocks_visible_read)
                resource = history.pages[0]
                entered, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
                releases.append(release)
                retired = resource.fragment_views[-1]
                retired.unmount_receipt = entered, release, finished
                retired_task = retired._task
                async with view.window.history_lock:
                    async with view.window.preserve_history(None):
                        resource.trim(1, older=False)
                async with asyncio.timeout(5):
                    await entered.wait()
                checks["trim_commits_before_original_unmount"] = (
                    retired not in resource.fragment_views and retired in resource.children
                    and retired not in app.screen._compositor.visible_widgets and not finished.is_set())
                history.finish_source_work(operation)
                operation = None
                checks["live_unloaded_tail_blocks_visible_read"] = (
                    history.state.accepts_source_work and history.has_newer
                    and history.blocks_visible_read)
                operation = history.reserve_source_work()
                snapshot = history.source_snapshot()
                selected = resource.update_slice(resource.fragments, True)
                assert await resource.update_fragments(page, resource.fragments, selected,
                                                       lambda: snapshot.current(history))
                checks["replacement_progresses_while_retired_child_attached"] = (
                    retired in resource.children and retired not in resource.fragment_views
                    and tuple(child.fragment for child in resource.fragment_views)
                    == resource.fragments[resource.start:resource.stop] and not finished.is_set())
                await history._jump_latest(LatestViewportRequest(view.window.scroll_revision))
                checks["end_commits_destination_without_old_unmount_join"] = (
                    history.pages[-1].stop == len(resource.fragments) and not finished.is_set())
                history.finish_source_work(operation)
                operation = None
                checks["live_settled_tail_releases_visible_read_fence"] = (
                    history.state.accepts_source_work and not history.has_newer
                    and history.checkpoint_available and not history.blocks_visible_read)
                operation = history.reserve_source_work()
                editor = view.prompt.prompt_text_area
                original_text = editor.text
                editor.focus(scroll_visible=False)
                await app._press_keys("x")
                pumped = asyncio.Event()
                view.call_later(pumped.set)
                async with asyncio.timeout(5):
                    await pumped.wait()
                checks["editor_and_source_pump_progress_during_unmount"] = (
                    editor.text == original_text + "x" and not view.window.history_lock.locked())
                resized = asyncio.Event()
                size = Size(112, 36)
                app._driver._size = size
                app.post_message(events.Resize(size, size))
                app.call_later(resized.set)
                async with asyncio.timeout(5):
                    await resized.wait()
                checks["resize_pump_progresses_before_unmount_completion"] = not finished.is_set()
                release.set()
                async with asyncio.timeout(5):
                    await finished.wait()
                    await asyncio.shield(retired_task)
                checks["original_child_unmount_and_unregister_complete"] = retired.parent is None

                # Cancellation at a genuine leaf Mount must not transfer the
                # page's tentative native children into committed membership.
                resource.trim(1, older=True)
                before_rows, before_bounds = resource.fragment_views, resource.capture_admission()
                mount_entered, mount_release = asyncio.Event(), asyncio.Event()
                releases.append(mount_release)
                original_body = resource._body
                resource._body = lambda fragment: PendingFragment(
                    fragment, resource.visible_categories, mount=(mount_entered, mount_release))
                snapshot = history.source_snapshot()
                task = asyncio.create_task(resource.extend(True, lambda: snapshot.current(history)))
                tasks.append(task)
                async with asyncio.timeout(5):
                    await mount_entered.wait()
                acquiring = tuple(child for child in resource.children if child not in before_rows)
                acquiring_tasks = tuple(child._task for child in acquiring)
                task.cancel()
                result = (await asyncio.gather(task, return_exceptions=True))[0]
                checks["cancelled_mount_keeps_committed_rows_and_bounds"] = (
                    isinstance(result, asyncio.CancelledError)
                    and resource.fragment_views == before_rows and resource.capture_admission() == before_bounds
                    and bool(acquiring) and all(child._pruning for child in acquiring))
                resource._body = original_body
                mount_release.set()
                await asyncio.gather(*acquiring_tasks, return_exceptions=True)

                page_entered, page_release = asyncio.Event(), asyncio.Event()
                releases.append(page_release)
                PendingPage.mount_receipt = page_entered, page_release
                before_pages = tuple(history.pages)
                snapshot = history.source_snapshot()

                async def acquire_page():
                    async with PendingPage.acquire(
                        history, page, fragments=resource.fragments,
                        batch_size=resource.batch_size, before=history.newer,
                        current=lambda: snapshot.current(history),
                    ) as acquired:
                        history.pages.append(acquired)

                task = asyncio.create_task(acquire_page())
                tasks.append(task)
                try:
                    async with asyncio.timeout(5):
                        await page_entered.wait()
                    acquiring_pages = tuple(child for child in history.children
                                            if isinstance(child, PendingPage) and child not in before_pages)
                    acquiring_page_tasks = tuple(child._task for child in acquiring_pages)
                    task.cancel()
                    result = (await asyncio.gather(task, return_exceptions=True))[0]
                    checks["cancelled_page_mount_does_not_commit_native_candidate"] = (
                        isinstance(result, asyncio.CancelledError) and tuple(history.pages) == before_pages
                        and resource.fragment_views == before_rows and resource.capture_admission() == before_bounds
                        and bool(acquiring_pages) and all(child._pruning for child in acquiring_pages))
                finally:
                    PendingPage.mount_receipt = None
                    page_release.set()
                await asyncio.gather(*acquiring_page_tasks, return_exceptions=True)

                # Both projections borrow original prepared-source ownership;
                # late removal of the first cannot clear the second admission.
                projections = []
                for _ in range(2):
                    source_projection = history.projected_source(history.selected_categories)
                    prepared = await source_projection.boundary()
                    overlay = ProjectedTranscriptHistory(history, source_projection, prepared)
                    if not projections:
                        history.finish_source_work(operation)
                        operation = None
                    history.filter.state = admitted = Filtered(overlay)
                    await history.mount(overlay, before=history.newer)
                    assert overlay.blocks_visible_read and history.blocks_visible_read
                    projections.append(admitted)
                checks["admitted_projection_blocks_live_canonical_read"] = (
                    history.state.accepts_source_work and not history.checkpoint_available
                    and history.blocks_visible_read and projections[-1].view.blocks_visible_read)
                stale, newer_state = projections
                stale_task, newer_task = (state.view._task for state in projections)
                checks["superseded_attached_projection_has_no_visible_read_obligation"] = (
                    stale.view.is_attached and not stale.view._pruning
                    and not stale.view.blocks_visible_read and newer_state.view.blocks_visible_read)
                stale.remove(history.filter)
                checks["stale_filter_cleanup_preserves_newer_admission"] = (
                    history.filter.state is newer_state and stale.view._pruning
                    and history.filter.owns_projection(newer_state.view) and not newer_state.view._pruning)
                await asyncio.gather(stale_task, return_exceptions=True)
                history.filter.remove()
                checks["settled_filter_restores_live_source_fence"] = (
                    history.checkpoint_available and not history.has_newer
                    and not history.blocks_visible_read)
                operation = history.reserve_source_work()
                await asyncio.gather(newer_task, return_exceptions=True)

                source_cases = []
                for cause in ("revision", "parked", "loader", "pruning"):
                    read_entered, read_release = asyncio.Event(), asyncio.Event()
                    releases.append(read_release)

                    async def loader(**kwargs):
                        read_entered.set()
                        await read_release.wait()
                        return page

                    prefix = TranscriptPage(page.events[-1:], TranscriptCursor(source, 32),
                                            TranscriptCursor(source, 33), True, False)
                    pending = TranscriptHistory(prefix, loader)
                    pending.pages[0] = PendingPage(prefix)
                    await view.post(pending)
                    pending_operation = pending.reserve_source_work()
                    assert pending.state is pending_operation and pending.blocks_visible_read
                    before_pages, before_rows = tuple(pending.pages), pending.fragment_views
                    task = asyncio.create_task(pending._load_page(True))
                    tasks.append(task)
                    async with asyncio.timeout(5):
                        await read_entered.wait()
                    if cause == "revision":
                        pending.invalidate_projection()
                    elif cause == "parked":
                        await pending.retire_source(parked=True)
                        checks["parked_attached_source_has_no_visible_read_obligation"] = (
                            pending.is_attached and not pending.blocks_visible_read)
                    elif cause == "loader":
                        async def replacement(**kwargs):
                            return page
                        pending.loader = replacement
                    else:
                        unmount_entered, unmount_release, unmount_finished = (
                            asyncio.Event(), asyncio.Event(), asyncio.Event())
                        releases.append(unmount_release)
                        pending.fragment_views[0].unmount_receipt = (
                            unmount_entered, unmount_release, unmount_finished)
                        pending_task = pending._task
                        removal = pending.remove()
                        async with asyncio.timeout(5):
                            await unmount_entered.wait()
                        checks["pruned_working_source_releases_fence_before_unmount"] = (
                            pending.is_attached and pending in view.window.histories
                            and pending._pruning and not pending.checkpoint_available
                            and not pending.blocks_visible_read and not unmount_finished.is_set())
                    read_release.set()
                    result = (await asyncio.gather(task, return_exceptions=True))[0]
                    assert result is None or isinstance(result, asyncio.CancelledError), result
                    assert tuple(pending.pages) == before_pages and pending.fragment_views == before_rows
                    source_cases.append(cause)
                    if cause == "pruning":
                        unmount_release.set()
                        await removal
                        await asyncio.shield(pending_task)
                        checks["pruned_source_original_unmount_unregister_complete"] = (
                            pending.parent is None and pending not in view.window.histories)
                    else:
                        await pending.remove()
                checks["original_revision_park_loader_fences_reject_late_read"] = (
                    source_cases[:3] == ["revision", "parked", "loader"])
                checks["original_pruning_fence_rejects_late_read"] = source_cases[-1] == "pruning"
                assert all(checks.values()), checks
                assert view.agent is None and app._exception is None
            finally:
                for release in releases:
                    release.set()
                PendingPage.mount_receipt = None
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if operation is not None:
                    history.finish_source_work(operation)
                (output / "progress.json").write_text(json.dumps({
                    "checks": checks, "toad_package": str(package),
                    "exception": str(app._exception),
                }, indent=2) + "\n")
        checks["whole_original_app_shutdown"] = app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    receipt = {"scope": "Installed original App/page/Mount/Unmount/source/read-fence custody; no backend painted-cursor writer, physical, CPU or FPS claim",
               "checks": checks, "toad_package": str(package), "source_cases": source_cases,
               "provider_inputs": 0, "native_inputs": 0, "exception": str(app._exception)}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
