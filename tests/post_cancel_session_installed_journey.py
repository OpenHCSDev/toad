"""Cancel actual native inputs, then exercise ACP controls and a distinct input."""
import asyncio
import json
import os
import threading
from pathlib import Path

from agent_comms.input_disposition import InputDispositions
from agent_comms.native_startup import NativeStartupAdmission, NATIVE_STARTUP_POLICY
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import submit_editor, screen_paint


stream_started, stream_release = threading.Event(), threading.Event()


def after_chunk(request_number, index):
    if request_number == 2 and index == 0:
        stream_started.set()
        assert stream_release.wait(20), 'UI did not release accepted stream'


def reply(request, number):
    return ({'role': 'assistant', 'content': ('ACCEPTED_STREAM_PARTIAL_' + 'remainder ' * 300
                                             if number == 2 else f'NATIVE_RESPONSE_{number}')}, 'stop')


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    evidence = Path(os.environ['L0A_EVIDENCE'])
    records = []
    leases = [NativeStartupAdmission(comms.root) for _ in range(NATIVE_STARTUP_POLICY.slots)]
    try:
        for lease in leases:
            await lease.acquire()
        await submit_editor(pilot, view.prompt.prompt_text_area, 'CANCEL_BEFORE_NATIVE_SEND')
        await until(pilot, lambda: comms.registry.require('beta').executing and view.turns.owner.busy)
        await pilot.pause(.15)
        assert not requests, 'Startup admission failed to hold native send'
        await pilot.press('escape', 'escape')
        await until(pilot, lambda: not comms.registry.require('beta').executing and agent.presentation.prompt_in_flight == 0)
        await until(pilot, lambda: 'Not sent — cancellation completed before native delivery' in screen_paint(app))
        assert all(row.public_status == 'not_sent' for row in InputDispositions(comms.root / InputDispositions.filename).read().rows.values())
        records.append({'stage': 'before_send', 'rows': [row.public() for row in InputDispositions(comms.root / InputDispositions.filename).read().rows.values()], 'paint': screen_paint(app)})
    finally:
        for lease in leases:
            lease.release()
    (evidence / 'cancel-stages.json').write_text(json.dumps(records, indent=2))
    # Controls are actual session/set_config_option requests. They must remain usable
    # after cancellation; these are fresh fixture actions, never original retries.
    await agent.set_model('selected-offline/fixture')
    await agent.set_thinking_level('off')
    await submit_editor(pilot, view.prompt.prompt_text_area, 'CANCEL_PROVIDER_INFLIGHT')
    await until(pilot, entered.is_set)
    assert len(requests) == 1
    await pilot.press('escape', 'escape')
    await until(pilot, lambda: not comms.registry.require('beta').executing and agent.presentation.prompt_in_flight == 0)
    await until(pilot, lambda: 'Native input started; turn cancelled' in screen_paint(app))
    records.append({'stage': 'provider_inflight', 'rows': [row.public() for row in InputDispositions(comms.root / InputDispositions.filename).read().rows.values()], 'paint': screen_paint(app)})
    (evidence / 'cancel-stages.json').write_text(json.dumps(records, indent=2))
    release.set()
    await agent.set_model('selected-offline/fixture')
    await agent.set_thinking_level('off')
    await submit_editor(pilot, view.prompt.prompt_text_area, 'CANCEL_ACCEPTED_PARTIAL_REPLY')
    await until(pilot, stream_started.is_set)
    await until(pilot, lambda: 'ACCEPTED_STREAM_PARTIAL_' in screen_paint(app))
    await pilot.press('escape', 'escape')
    await until(pilot, lambda: not comms.registry.require('beta').executing and agent.presentation.prompt_in_flight == 0)
    await until(pilot, lambda: screen_paint(app).count('Native input started; turn cancelled') >= 2)
    records.append({'stage': 'accepted_partial_reply', 'rows': [row.public() for row in InputDispositions(comms.root / InputDispositions.filename).read().rows.values()], 'paint': screen_paint(app)})
    (evidence / 'cancel-stages.json').write_text(json.dumps(records, indent=2))
    stream_release.set()
    await agent.set_model('selected-offline/fixture')
    await agent.set_thinking_level('off')
    await submit_editor(pilot, view.prompt.prompt_text_area, 'DISTINCT_MESSAGE_AFTER_CANCEL')
    await until(pilot, lambda: len(requests) == 3)
    await until(pilot, lambda: not comms.registry.require('beta').executing and agent.presentation.prompt_in_flight == 0)
    await until(pilot, lambda: 'NATIVE_RESPONSE_3' in screen_paint(app))
    assert len(requests) == 3, 'Cancelled input was replayed'
    assert 'Internal error' not in screen_paint(app)
    records.append({'stage': 'new_message', 'rows': [row.public() for row in InputDispositions(comms.root / InputDispositions.filename).read().rows.values()], 'paint': screen_paint(app)})
    (evidence / 'cancel-stages.json').write_text(json.dumps(records, indent=2))


if __name__ == '__main__':
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance,
                              expected_response_disconnects=frozenset({1, 2}),
                              provider_reply=reply, provider_chunk_characters=40,
                              provider_after_chunk=after_chunk))
