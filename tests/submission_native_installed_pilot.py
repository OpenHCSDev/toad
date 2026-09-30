"""Warm saved history -> native rename -> physical queued send -> reply and return."""
import asyncio
import json
import os
from importlib.resources import files
from pathlib import Path
from agent_comms.input_disposition import InputDispositions
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from saved_state_user_journey_pilot import click_tab, screen_paint
from toad.navigation_target import channel_target, NavigationContext
from toad.widgets.prompt import QueueSummary
from toad.widgets.user_input import UserInput

class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


def reply(request, number):
    if number == 1:
        names = [tool['function']['name'] for tool in request.get('tools', ())]
        assert 'comms_rename_self' in names, names
        return {'role': 'assistant', 'tool_calls': [{
            'index': 0, 'id': 'native-rename', 'type': 'function',
            'function': {'name': 'comms_rename_self',
                         'arguments': json.dumps({'new_name': 'renamed-beta'})},
        }]}, 'tool_calls'
    return {'role': 'assistant', 'content': f'NATIVE_RESPONSE_{number}'}, 'stop'


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    mode = app.selected_mode
    release.set(); hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    view.prompt.text = 'SUBMISSION_SAVED_HISTORY_AND_RENAME'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_2'), 30)
    await until(pilot, lambda: not comms.registry.require('renamed-beta').executing)
    assert agent.session_id == 'beta'
    assert comms.registry.canonical_name('beta') == 'renamed-beta'
    await agent.session.reconnect()
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, 'NATIVE_RESPONSE_2'))
    # Return through physical tabs before another native turn. Reuse the saved
    # view and real editor; no refresh input is sent to paint the native history.
    await channel_target('#team').open(NavigationContext(app, mode, agent.project_root_path,
        comms.messaging.user_identity(str(agent.project_root_path)).name))
    channel = app.selected_session
    await click_tab(app, pilot, mode)
    assert app.selected_session.conversation is view
    entered.clear(); release.clear(); hold_next.set()
    view.prompt.text = 'SUBMISSION_ORDINARY_AFTER_RENAME'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, entered.is_set)
    await until(pilot, lambda: view.turns.owner.busy)
    view.prompt.text = 'SUBMISSION_DEFERRED_AFTER_RENAME'
    await pilot.press('enter')
    await until(pilot, lambda: bool(agent.queue_attachment.projection.items))
    queued = agent.queue_attachment.projection.items[0]
    assert queued.text == 'SUBMISSION_DEFERRED_AFTER_RENAME'
    assert queued.text in view.query_one(QueueSummary).render().plain
    assert not view.prompt.text
    scope = agent.queue_attachment.scope
    assert scope.session_id == 'beta' and scope.owner.incarnation.name == 'renamed-beta'
    # Keep the actual queued turn open during another A/B/A reader return.
    view.prompt.text = 'SUBMISSION_UNSENT_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    await click_tab(app, pilot, channel.id)
    await click_tab(app, pilot, mode)
    assert view.prompt.prompt_text_area.document is document
    assert view.prompt.prompt_text_area.history is undo
    assert view.prompt.text == 'SUBMISSION_UNSENT_DRAFT'
    await pilot.press('ctrl+y')
    release.set()
    await until(pilot, lambda: not comms.registry.require('renamed-beta').executing and len(requests) == 4, 30)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_4'))
    # Original visible input is admitted from its native start receipt, once.
    await until(pilot, lambda: queued.text in screen_paint(app))
    assert not agent.queue_attachment.projection.items
    assert not view.submissions.active
    disposition = InputDispositions(comms.root / InputDispositions.filename).read().rows['acp:' + queued.input_id]
    assert not disposition.unresolved and disposition.native_id
    assert view.prompt.text == 'SUBMISSION_UNSENT_DRAFT'
    assert agent.queue_attachment.scope.relation(scope).current
    delivery = await agent.controller.input_delivery(include_history=True)
    assert delivery['inputs'] == [], delivery
    assert await agent.get_goal_snapshot() == (None, None)
    assert agent.controller.prompt_in_flight == 0
    assert not agent.controller._deferred_submissions
    log = agent.presentation.log_path.read_text()
    assert log.count("'kind': 'send_now'") == 1
    root = Path(os.environ['L0A_EVIDENCE'])
    (root / 'submission.svg').write_text(app.export_screenshot())
    (root / 'submission.json').write_text(json.dumps({
        'requests': len(requests), 'sessionId': agent.session_id,
        'owner': agent.queue_attachment.scope.owner.incarnation.name,
        'inputId': queued.input_id, 'inputState': disposition.public_status,
        'draftPreserved': view.prompt.text == 'SUBMISSION_UNSENT_DRAFT',
        'paint': screen_paint(app),
    }, indent=2))
    print('PASS actual installed native rename, saved history, warm physical A/B/A, busy queue/start/input paint/first reply, no replay; four loopback requests', flush=True)

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance, provider_reply=reply,
                    provider_request_budget=4, expected_response_disconnects=frozenset({3})))
