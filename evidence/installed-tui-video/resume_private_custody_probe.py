"""Complete an interrupted private fixture check without replaying any input.

Reuse the existing fixture's loopback handler on its original port, then attach
its surviving exact owner through installed ACP. No capture or owner restart.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.environ['VIDEO_FIXTURE_TESTS'])
import l0a_native_installed_pilot as fixture
from saved_state_user_journey_pilot import SavedStateSubscriber
from agent_comms.acp import CommsClient
from agent_comms.comms import Comms
from agent_comms.input_disposition import InputDispositions
from acp.schema import TextContentBlock

EVIDENCE = Path(os.environ['VIDEO_RESUME_EVIDENCE'])
RECEIPT = json.loads((EVIDENCE / 'private-startup/receipt.json').read_text())
ROUTE = RECEIPT['runtime_before']['observed']['route']
PROJECT = Path(RECEIPT['command'][3])
STAGE = PROJECT.parent
PORT = urlparse(json.loads((STAGE / 'pi/models.json').read_text())['providers']['selected-offline']['baseUrl']).port
NEW_INPUT = 'NEW_PRIVATE_POST_CAPTURE_CUSTODY_INPUT_AFTER_SERVER_RESTART_20260929'
RESPONSE = 'PRIVATE_POST_CAPTURE_RESUME_RESPONSE_CONFIRMED'
REAL_SERVER = fixture.ThreadingHTTPServer


class Accepted(BaseException):
    pass


def existing_port(address, handler):
    assert address[0] == '127.0.0.1'
    return REAL_SERVER(('127.0.0.1', PORT), handler)


async def check(unused_comms, unused_project, requests, entered, release, hold_next):
    # The provider fixture supplies only its existing bounded loopback handler.
    # Its fresh declared (unstarted) owner is unrelated to the surviving owners.
    release.set()
    hold_next.clear()
    os.environ.update(AGENT_COMMS_ROOT=ROUTE['root'],
                      AGENT_COMMS_PRIVATE_NK_WIRE_ROOT_ID=ROUTE['wire_root_id'],
                      AGENT_COMMS_PRIVATE_NK_NATIVE_PACKAGE=ROUTE['native_package'])
    comms = Comms(Path(ROUTE['root']), private_initial_writes=False, private_claim_writes=False)
    expected = json.loads((EVIDENCE / 'custody-acceptance.json').read_text())['owner_checks'][0]['owners']
    before = {}
    for name, recorded in expected.items():
        thread = comms.registry.require(name)
        identity = thread.process_identity
        assert identity.pid == recorded['pid'] and identity.start_time == recorded['start_ticks']
        assert identity.alive() and not thread.executing
        before[name] = identity
    dispositions = InputDispositions(comms.root / InputDispositions.filename)
    document = dispositions.read()
    assert not document.unknown(frozenset(before)), 'Unresolved original input blocks this check'
    assert not any(NEW_INPUT in row.source_text for row in document.rows.values()), 'Check already attempted; do not replay'
    client = CommsClient(comms, runtime_enabled=True,
                         private_nk_native_package=Path(ROUTE['native_package']),
                         private_nk_wire_root_id=ROUTE['wire_root_id'])
    subscriber = SavedStateSubscriber()
    client.on_connect(subscriber)
    try:
        async with asyncio.timeout(25):
            await client.load_session(cwd=str(PROJECT), session_id='beta')
            assert comms.registry.require('beta').process_identity == before['beta']
            await client.prompt('beta', [TextContentBlock(type='text', text=NEW_INPUT)])
        subscriber.require_success()
        assert len(requests) == 1
        native = Path(comms.registry.require('beta').session_file).read_text()
        assert NEW_INPUT in native and RESPONSE in native
        assert not dispositions.read().unknown(frozenset(before))
        for name, identity in before.items():
            assert identity.alive() and comms.registry.require(name).process_identity == identity
        result = {'assessment': 'custody accepted; video assessment separate',
                  'original_owners': expected, 'attachable_after_capture': True,
                  'new_controlled_input_worked': True, 'new_input': NEW_INPUT,
                  'new_loopback_provider_requests': 1, 'replayed_input': False,
                  'capture_receipts': ['private-startup', 'private-profiled', 'private-unprofiled'],
                  'recovery': 'Original fixture parent/provider lost at server restart; existing provider handler restored on its original loopback port. Exact original owners retained.',
                  'cleanup': 'Private fixture lifecycle teardown follows recorded acceptance; no owner restart'}
        (EVIDENCE / 'custody-resume-acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
        saved = EVIDENCE / 'retained-native-sessions'
        saved.mkdir(exist_ok=True)
        for name in before:
            shutil.copy2(comms.registry.require(name).session_file, saved / f'{name}.jsonl')
        print('EXACT_OWNERS_SURVIVED_CAPTURE_ATTACH_AND_NEW_LOOPBACK_INPUT', flush=True)
    finally:
        await client.shutdown()
    # Only this private fixture's original exact owners are disposed by Core.
    for name, identity in before.items():
        assert comms.registry.require(name).process_identity == identity
        await asyncio.to_thread(comms.owners.stop, name)
        assert not identity.alive()
    result['private_owners_stopped_by_fixture_lifecycle'] = True
    (EVIDENCE / 'custody-resume-acceptance.json').write_text(json.dumps(result, indent=2) + '\n')
    raise Accepted()


async def main():
    fixture.ThreadingHTTPServer = existing_port
    try:
        await fixture.main(prepare_state=check, provider_request_budget=1,
                           provider_reply=lambda request, number: ({'role': 'assistant', 'content': RESPONSE}, 'stop'))
    except Accepted:
        pass
    finally:
        fixture.ThreadingHTTPServer = REAL_SERVER


if __name__ == '__main__':
    asyncio.run(main())
