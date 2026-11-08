"""Real read-ledger refusal through the shared Textual read worker, not a fake error."""

import asyncio

import pytest

from agent_comms.storage.maintenance_barrier import MaintenanceOperator, NoMaintenanceHolder
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
                for paint in range(3):
                    with source.open("a", encoding="utf-8") as output:
                        output.write(f"Fresh paint during maintenance {paint}\n")
                    painted = source.stat()
                    worker = ReadWork(asyncio.to_thread(
                        ledger.mark_transcript, viewer, str(source), painted.st_ino,
                        painted.st_size, painted.st_size,
                    )).start(marker)
                    await worker.wait()
                    await ui.step()
                    assert ledger.read() == original
                    assert ledger.transcript_seen(viewer, str(source), first.st_ino) == 0
                    assert not ui.reported_errors()
                    assert not ui.shows("Read not marked")
                    assert ui.failure() is None
            finally:
                barrier.clear(hold)

            # A new source/cursor observation after relief, not an automatic replay.
            with source.open("a", encoding="utf-8") as output:
                output.write("Newly painted row after maintenance\n")
            fresh = source.stat()
            worker = ReadWork(asyncio.to_thread(
                ledger.mark_transcript, viewer, str(source), fresh.st_ino,
                fresh.st_size, fresh.st_size,
            )).start(marker)
            await worker.wait()
            assert ledger.transcript_seen(viewer, str(source), fresh.st_ino) == fresh.st_size
            assert not ui.reported_errors()
            assert ui.failure() is None


async def test_unexpected_read_failure_still_raises(workspace):
    async def failed_read():
        raise OSError("Read source failed")

    async with workspace.app(size=(100, 35), notifications=True) as ui:
        with pytest.raises(OSError, match="Read source failed"):
            await ReadWork(failed_read()).run(ui.app.selected_session)
