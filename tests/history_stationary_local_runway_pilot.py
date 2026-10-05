"""A complete native source page prepares its unmounted idle neighbors.

Actual Toad application, native history/page/body custody and render workers.
The admitted operation holds foreground paging, so this counter distinguishes
background preparation from moving or mounting the reader. No Agent/provider.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

if "--installed-only" not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from toad.app import ToadApp
from toad.widgets.transcript_fragments import TranscriptBodyPreparation
from toad.widgets.transcript_history import TranscriptHistory
from toad.widgets.presentation_window import MovingPreparation
from toad.widgets.comms_chat import session_thread_name
from textual.worker import WorkerCancelled, get_current_worker


async def main(output, *, worker_custody=False):
    output.mkdir(parents=True, exist_ok=False)
    if "--installed-only" in sys.argv:
        import importlib.metadata as metadata
        import toad
        package = Path(metadata.distribution("batrachian-toad").locate_file("toad")).resolve()
        assert Path(toad.__file__).resolve().parent == package
        assert package.is_relative_to(Path(sys.prefix).resolve())
    observations = []
    workers_seen = []
    custody = {}
    entered, release = asyncio.Event(), asyncio.Event()
    if not worker_custody:
        release.set()
    prepare_fragments = TranscriptBodyPreparation.prepare_fragments

    async def observe(preparation, fragments, keep_going, *, batch_size):
        workers_seen.append(get_current_worker())
        entered.set()
        await release.wait()
        await prepare_fragments(preparation, fragments, keep_going, batch_size=batch_size)
        observations.append(tuple(fragments))

    with TemporaryDirectory(dir=output) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"),
                          XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"))
        service = Comms(root / "wire")
        service.messaging.initialize_private_initial_protocol()
        service.registry.declare(Thread(session_thread_name(root), frozenset(), str(root)))
        # Seed the original typed page contract, not a hand-authored journal
        # decoder. The installed physical gate owns real saved-source proof.
        source = str(root / "saved-source")
        page = TranscriptPage(tuple(AssistantTranscript(
            f"## Original saved record {index}\n\n"
            + "\n\n".join(f"Local runway paragraph {row}." for row in range(4)),
        ) for index in range(32)), TranscriptCursor(source, 0),
            TranscriptCursor(source, 32), False, False)
        reads = []

        async def loader(**kwargs):
            reads.append(kwargs)
            raise AssertionError("A complete source must not request a transport page")

        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(110, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            view = app.selected_session.conversation
            await view.transcript.suspend()
            viewport = view.window.document_viewport
            await viewport.suspend_source()
            viewport.lookahead.settle()
            history = TranscriptHistory(page, loader=loader)
            operation = history.reserve_source_work()
            if worker_custody:
                # Authored demand data exercises the actual source worker;
                # this is not a physical wheel or frame-time measurement.
                viewport.lookahead.demand = MovingPreparation(-1)
            TranscriptBodyPreparation.prepare_fragments = observe
            try:
                await view.post(history)
                if worker_custody:
                    await asyncio.wait_for(entered.wait(), 10)
                    first = next(history.lookahead_workers())
                    demand = viewport.lookahead.demand
                    before = viewport.lookahead.preparation_count(view.window.size.height)
                    demand.velocity = (-app.preparation.max_entries * viewport.visible_body_rows
                                       / viewport.budget.lookahead_seconds)
                    after = viewport.lookahead.preparation_count(view.window.size.height)
                    history.prepare_scroll()
                    custody["extent_changed"] = after > before
                    custody["same_direction_original_worker_retained"] = tuple(history.lookahead_workers()) == (first,)
                    assert all(custody.values())
                    release.set()
                    await asyncio.wait_for(first.wait(), 10)

                    entered.clear()
                    release.clear()
                    demand.velocity = -1
                    history.prepare_scroll()
                    await asyncio.wait_for(entered.wait(), 10)
                    reverse = next(history.lookahead_workers())
                    viewport.lookahead.observe(viewport.lookahead.position + view.window.size.height)
                    history.prepare_scroll()
                    successor = next(history.lookahead_workers())
                    custody["reversal_replaced_original_worker"] = successor is not reverse
                    try:
                        await asyncio.wait_for(reverse.wait(), 10)
                    except WorkerCancelled:
                        custody["revoked_waiter_joined"] = True
                    else:
                        raise AssertionError("Reversal retained the obsolete preparation waiter")
                    await history.retire_source()
                    custody["retirement_closed_reader"] = history._page_buffer.closed
                    custody["retirement_joined_successor"] = successor.is_finished
                    release.set()
                    assert all(custody.values())
                await pilot.pause(.05)
                resource = history.pages[0]
                admission = resource.capture_admission()
                children = tuple(resource.fragment_views)
                worker = workers_seen[0] if workers_seen else None
                if worker is not None and not worker_custody:
                    await asyncio.wait_for(worker.wait(), 10)
                prepared = tuple(fragment for batch in observations for fragment in batch)
                prepared_indexes = [resource.fragments.index(fragment) for fragment in prepared]
                receipt = {
                    "scope": "actual source Toad/native idle preparation; not installed physical acceptance",
                    "worker_custody": custody,
                    "transport_has_older": page.has_older,
                    "transport_has_newer": page.has_newer,
                    "travel_rows": viewport.lookahead.travel_rows,
                    "local_unmounted_fragments": resource.start,
                    "admitted_range": [admission.start, admission.stop],
                    "prepared_indexes": prepared_indexes,
                    "idle_local_worker_exists": worker is not None,
                    "original_children_unchanged": tuple(resource.fragment_views) == children,
                    "original_admission_unchanged": resource.capture_admission() == admission,
                    "transport_reads": len(reads),
                    "prepared_bytes": app.preparation.retained_bytes,
                    "byte_bound": app.preparation.max_bytes,
                    "agent_bound": view.agent is not None,
                    "exception": str(app._exception),
                }
                (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                print(json.dumps(receipt), flush=True)
                assert not page.has_older and not page.has_newer
                assert resource.start > 0
                if not worker_custody:
                    assert not viewport.lookahead.travel_rows
                assert worker is not None and prepared_indexes, "Idle local source runway was skipped"
                assert all(index < admission.start or index >= admission.stop for index in prepared_indexes)
                assert tuple(resource.fragment_views) == children and resource.capture_admission() == admission
                assert not reads and app.preparation.retained_bytes <= app.preparation.max_bytes
                assert view.agent is None and app._exception is None
            finally:
                release.set()
                TranscriptBodyPreparation.prepare_fragments = prepare_fragments
                history.finish_source_work(operation)
                workers_seen.clear()
        await asyncio.get_running_loop().shutdown_default_executor()
        receipt["whole_original_App_shutdown"] = True
        receipt["app_exception"] = str(app._exception)
        assert app._exception is None
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[-1]), worker_custody="--worker-custody" in sys.argv))
