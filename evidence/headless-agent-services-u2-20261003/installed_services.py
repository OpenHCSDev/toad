"""Changed original service lifetime through installed ACP/Pi/Textual owners."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from client_session_native_installed_pilot import InstalledApp as NativeInstalledApp, acceptance as client_acceptance
from l0a_native_installed_pilot import main
from toad.acp.agent import Agent

class InstalledApp(NativeInstalledApp):
    @asynccontextmanager
    async def run_test(self, **kwargs):
        async with super().run_test(**kwargs) as pilot:
            # Native session preparation mounts its view asynchronously. One
            # idle message queue is not the original content-ready contract.
            try:
                async with asyncio.timeout(20):
                    await self.selected_session.wait_content_ready()
                yield pilot
            except BaseException:
                import traceback
                Path(os.environ['L0A_EVIDENCE'], 'original-failure.txt').write_text(traceback.format_exc())
                raise

async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    started = time.monotonic()
    reader = agent.controller.transcripts
    async with reader.bind(str(comms.root)) as shared:
        assert shared is app.coordination_access.service
    # Cancellation releases the ORIGINAL resource's lock, before any input.
    async with reader._lock:
        pending = asyncio.create_task(reader.notifications(str(comms.root), ()))
        await asyncio.sleep(0)
        assert not pending.done()
        pending.cancel()
        result, = await asyncio.gather(pending, return_exceptions=True)
        assert isinstance(result, asyncio.CancelledError)
    async with reader.bind(str(comms.root)) as after_cancel:
        assert after_cancel is shared
    await client_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests)
    assert agent.controller.transcripts is reader
    async with reader.bind(str(comms.root)) as after_return:
        assert after_return is shared
    Path(os.environ['L0A_EVIDENCE'], 'service-lifetime-receipt.json').write_text(json.dumps({
        'result':'PASS', 'elapsed_seconds':time.monotonic()-started,
        'native_requests':len(requests), 'same_reader_after_reconnect_detach_return':True,
        'same_canonical_service_after_cancel_and_return':True,
        'cancelled_read_released_original_lock':True,
        'permissions_original_future_retained_and_answered':True,
        'terminal_original_execution_retained_and_released':True,
        'saved_response_and_draft_document_undo_retained':True,
        'agent_source':str(Path(sys.modules[Agent.__module__].__file__).resolve()),
        'scope':'Real installed Toad/ACP/Pi; Textual Pilot; one controlled localhost native answer plus real registered client file/permission/terminal requests; no public input or paid provider.'
    },indent=2)+'\n')

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance,
        fixture_stage=os.environ['U2_FIXTURE_ROOT'], provider_request_budget=1,
        provider_reply=lambda request, number: (
            {'role':'assistant','content':f'NATIVE_RESPONSE_{number}'}, 'stop')))
