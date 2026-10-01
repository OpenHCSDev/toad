"""Current human origin through the original Toad/ACP/native input journey.

Run with the normal matched installation, or explicitly label a source-path
control. The existing driver owns the actual app, provider, native children and
cleanup; this adds assertions on original authorities, never substitutes them.
"""

import asyncio
import json
import os
from pathlib import Path

from agent_comms.acp_extension import QueuePromptRequest
from agent_comms.field_codec import FieldCodec
from agent_comms.input_disposition import InputDispositions
from agent_comms.native_entries import NativeEntry
from agent_comms.retained_task_facts import CurrentHumanInputTaskFact
from toad.widgets.conversation import Conversation

from l0a_native_installed_pilot import main, until


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    evidence = Path(os.environ['L0A_EVIDENCE'])
    record = {'mode': os.environ['S2_ORIGIN_PROOF_MODE'], 'original_inputs_retried': 0,
              'core_import': __import__('agent_comms').__file__,
              'toad_import': __import__('toad').__file__, 'phases': []}

    def persist(phase):
        record['phases'].append(phase)
        (evidence / 'origin-journey.json').write_text(json.dumps(record, indent=2))

    view = app.screen.query_one(Conversation)
    await until(pilot, lambda: agent.queue_attachment.scope is not None)
    original_text = 'S2_ORIGINAL_HUMAN_INPUT: preserve UNKNOWN and original project.'
    view.prompt.text = original_text
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, entered.is_set)
    inputs = InputDispositions(comms.root / InputDispositions.filename)
    await until(pilot, lambda: len(inputs.read().rows) == 1)
    original, = inputs.read().rows.values()
    origin = original.origin.require_human()
    assert origin.root_id == comms.bus.log.read_metadata_unlocked().wire_root_id
    assert original.source_text == original_text
    origin.author.require_registered(comms.registry.snapshot())
    record['original'] = FieldCodec.encode(original)
    persist('actual_enter_original_authored_reservation')

    command = QueuePromptRequest('S2_FOLLOWING_HUMAN_INPUT: never replay the original.', True)
    await agent.send_prompt(command.user_text, request=command)
    await until(pilot, lambda: len(inputs.read().rows) == 2)
    following = inputs.read().lookup('acp:' + command.input_id)
    assert following.origin == origin and following.source_text == command.user_text
    record['following'] = FieldCodec.encode(following)
    persist('actual_acp_followup_same_original_author_two_reservations')

    release.set()
    await until(pilot, lambda: all(row.has_started for row in inputs.read().rows.values()), 30)
    await until(pilot, lambda: not comms.registry.require('beta').executing, 30)
    assert len(requests) == 2
    terminal = InputDispositions(inputs.path).read()
    assert len(terminal.rows) == 2
    assert all(row.origin == origin for row in terminal.rows.values())
    owner = comms.registry.require('beta')
    snapshot = comms.registry.snapshot()
    assert all(isinstance(row.origin.retained_fact(row).for_owner(owner, snapshot),
                          CurrentHumanInputTaskFact)
               for row in terminal.rows.values())
    record['terminal_inputs'] = FieldCodec.encode(terminal)
    persist('native_started_original_and_following_same_durable_source')

    source = Path(owner.require_saved_session())
    with NativeEntry.open_evidence(source) as evidence_read:
        header, entries = evidence_read.observe()
        record['native_header'] = FieldCodec.encode(header)
        record['native_entries'] = [FieldCodec.encode(entry) for entry in entries]
    assert {row.native_id for row in terminal.rows.values()} <= {
        entry.message.input_id for entry in entries if entry.is_message and entry.message.user}
    app.export_screenshot(filename=str(evidence / 'original-and-following.svg'))
    record['provider_requests'] = len(requests)
    record['complete'] = True
    persist('original_native_ids_corroborated_and_actual_frame_saved')


if __name__ == '__main__':
    asyncio.run(main(acceptance=acceptance,
        provider_reply=lambda request, index: ({'role': 'assistant',
            'content': f'S2_ORIGIN_ANSWER_{index}'}, 'stop'), provider_request_budget=2,
        fixture_stage=os.environ['S2_ORIGIN_FIXTURE']))
