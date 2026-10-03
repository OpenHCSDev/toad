"""Original493 notification, actual retained owner read and installed App paint.

No input or provider call. Only the already-recorded notification is delivered
again to this isolated frontend; its actual canonical source supplies settlement.
The held local callable checks owned-operation release, not native input delivery.
"""
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from manual_live_turn_status import acp_agent, ready
from saved_state_user_journey_pilot import screen_paint
from l0a_native_installed_pilot import until
from agent_comms.comms import wire
from agent_comms.field_codec import FieldCodec
from toad.app import ToadApp
from toad.acp.client_session import ClientSessionRequest
from toad.agent_schema import AgentDefinition
from toad.widgets.conversation import TurnActivity
from toad.widgets.throbber import Throbber
from toad.widgets.session_details import SessionDetails

LOG = Path('/home/ts/.local/state/toad/logs/Agent_Comms_2026-10-02T23_33_32_389243.txt')


def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def phase(view):
    return dict(busy=view.turns.owner.busy,
                phase=view.turns.owner.activity,
                activity_visible=view.query_one(TurnActivity).visible,
                prompt_busy=view.prompt.agent_busy,
                throbber_busy=view.query_one(Throbber).busy,
                view_work=view.busy_count,
                details=str(view.query_one(SessionDetails).title),
                local_requests=view.agent.controller.prompt_in_flight,
                cursor_status=view.agent._private_cursor.status)


async def main():
    evidence = Path(os.environ['SETTLEMENT_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    comms = wire()
    original = comms.registry.require('openhcs-helper')
    journal = Path(original.session_file)
    before_hash = digest(journal)
    events = [json.loads(line[line.index('{'):])
              for line in LOG.read_text().splitlines() if 'turn_changed' in line]
    assert len(events) == 1
    original_event = events[0]
    # Exact original source remains the same completed turn, not a substitute.
    recorded = original_event['params']['update']['_meta']['agentComms']['updates'][0]['state']
    assert original.turn_state.finished_turn_id == recorded['active']['id']
    assert original.active_turn is None
    envroot = evidence / 'frontend'
    for name, leaf in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                       ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache')]:
        os.environ[name] = str(envroot / leaf)
    os.environ['AGENT_COMMS_ROOT'] = str(comms.root)
    app = ToadApp(agent_data=AgentDefinition.decode(acp_agent()), project_dir=original.worktree,
                  agent_session_id=original.name)
    records = []
    async with app.run_test(size=(140, 38)) as pilot:
        source = app.selected_session
        view = await ready(pilot, app, source)
        agent = view.agent
        await until(pilot, lambda: view.agent_ready and agent.coordination is not None, 15)
        surface = agent.controller.surface
        current_cursor = agent._private_cursor.current
        await agent.get_thread_presentation()
        await pilot.pause()
        records.append(dict(stage='actual_retained_startup', **phase(view)))

        async def original_active():
            # Original SDK validator / registered notification endpoint / native
            # CoreEvent carrier, not a manually assigned phase or fake terminal.
            result = await agent.server.call(original_event)
            assert result is None or 'error' not in result, result
            await until(pilot, lambda: view.turns.owner.busy and
                        view.query_one(TurnActivity).visible, 5)
            assert 'Waiting for input start' in screen_paint(app)

        await original_active()
        records.append(dict(stage='captured_remote_active', **phase(view)))
        await agent.get_thread_presentation()
        await until(pilot, lambda: not view.turns.owner.busy and
                    not view.query_one(TurnActivity).visible, 5)
        assert not view.prompt.agent_busy
        assert 'Waiting for input start' not in screen_paint(app)
        records.append(dict(stage='canonical_remote_settlement', **phase(view)))
        (evidence / 'remote-settled.svg').write_text(app.export_screenshot())

        await original_active()
        entered, release = asyncio.Event(), asyncio.Event()
        async def held_owned_operation():
            entered.set()
            await release.wait()
        authority = ClientSessionRequest(agent, agent.session_id)
        operation = asyncio.create_task(agent.controller.operate(
            agent.controller._prompt_operation(held_owned_operation, authority)))
        try:
            await entered.wait()
            await agent.get_thread_presentation()
            await pilot.pause()
            assert agent.controller.prompt_in_flight == 1
            assert view.turns.owner.busy  # ordered custody rejected that read
            records.append(dict(stage='read_fenced_by_local_operation', **phase(view)))
        finally:
            release.set()
            await operation
        # No manual refresh: the original operation owner schedules its new read.
        await until(pilot, lambda: not view.turns.owner.busy and
                    not view.query_one(TurnActivity).visible, 10)
        assert agent.controller.surface is surface
        assert surface.owns(view)
        assert agent._private_cursor.current is current_cursor
        assert agent.controller.prompt_in_flight == 0
        assert not view.prompt.agent_busy
        assert 'Waiting for input start' not in screen_paint(app)
        records.append(dict(stage='owned_completion_automatic_settlement', **phase(view)))
        (evidence / 'automatic-settled.svg').write_text(app.export_screenshot())
        assert app._exception is None
        log = agent.presentation.log_path.read_text()
        assert "'method': 'session/prompt'" not in log
        client = agent.process.process
        client_pid = client.pid
    import psutil
    after = comms.registry.require(original.name)
    assert after.process_identity == original.process_identity
    assert after.turn_state == original.turn_state
    assert digest(journal) == before_hash
    assert not psutil.pid_exists(client_pid)
    import toad, agent_comms, textual
    (evidence / 'receipt.json').write_text(json.dumps(dict(
        result='PASS', elapsed=time.monotonic()-started,
        imports=dict(toad=toad.__file__, core=agent_comms.__file__, textual=textual.__file__),
        original_notification_log=str(LOG), original_turn=original.turn_state.finished_turn_id,
        stages=records, source_hash_before=before_hash, source_hash_after=digest(journal),
        original_native_owner_unchanged=True, owned_acp_client_absent=True,
        cursor_proof_object_unchanged=True, prompt_requests=0, provider_calls=0,
        scope='Installed App/ACP with actual configured retained native owner. Recorded original active notification only; no input replay. Local callable proves owned-operation ordering/re-read, not native send. Pilot paint, no physical pixel claim.'), indent=2)+'\n')
    print('PASS installed retained owner settlement, original views, automatic post-operation read, no input/provider, ACP cleanup', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
