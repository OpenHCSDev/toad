"""Real read-ledger refusal through the shared Textual read worker, not a fake error."""

import asyncio

from agent_comms.maintenance_barrier import MaintenanceOperator, NoMaintenanceHolder
from agent_comms.read_ledger import ReadLedger

from toad.widgets.message_notifications import ReadWork


async def test_maintenance_keeps_read_marks_and_fresh_work_succeeds(workspace):
    source = workspace.project / "read-metadata-control.txt"
    source.write_text("First painted row\n", encoding="utf-8")
    first = source.stat()
    viewer = workspace.viewer
    ledger = ReadLedger.at(workspace.comms.root)
    barrier = workspace.comms.owners.maintenance
    original = ledger.read()

    with NoMaintenanceHolder().selected():
        async with workspace.app(size=(100, 35), notifications=True) as ui:
            marker = ui.app.selected_session
            hold = barrier.begin(MaintenanceOperator.current())
            try:
                previous_workers = set(marker.workers)
                ReadWork(asyncio.to_thread(
                    ledger.mark_transcript, viewer, str(source), first.st_ino,
                    first.st_size, first.st_size,
                )).start(marker)
                worker, = set(marker.workers) - previous_workers
                await worker.wait()  # A WorkerFailed is a failed control, not a warning.
                await ui.until_shows("Read not marked")
                assert ledger.read() == original
                assert ledger.transcript_seen(viewer, str(source), first.st_ino) == 0
                assert ui.failure() is None
            finally:
                barrier.clear(hold)

            # A new source/cursor observation after relief, not an automatic replay.
            with source.open("a", encoding="utf-8") as output:
                output.write("Newly painted row after maintenance\n")
            fresh = source.stat()
            previous_workers = set(marker.workers)
            ReadWork(asyncio.to_thread(
                ledger.mark_transcript, viewer, str(source), fresh.st_ino,
                fresh.st_size, fresh.st_size,
            )).start(marker)
            worker, = set(marker.workers) - previous_workers
            await worker.wait()
            assert ledger.transcript_seen(viewer, str(source), fresh.st_ino) == fresh.st_size
            assert ui.failure() is None
