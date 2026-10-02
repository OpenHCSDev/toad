"""Warm saved history -> native rename -> physical queued send -> reply and return."""
import asyncio
import json
import os
import shlex
import sys
import traceback
from importlib.resources import files
from pathlib import Path
from agent_comms.input_disposition import InputDispositions
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from saved_state_user_journey_pilot import click_tab, screen_paint
from toad.navigation_target import channel_target, NavigationContext
from toad.widgets.prompt import QueueSummary, SendNow

provider_hold = None


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

    def _handle_exception(self, error):
        with Path(os.environ['L0A_EVIDENCE'], 'app-failure.txt').open('a') as log:
            log.write(''.join(traceback.format_exception(error)))
        super()._handle_exception(error)


def reply(request, number):
    if number == 2:
        provider_hold.set()
        names = [tool['function']['name'] for tool in request.get('tools', ())]
        assert 'bash' in names, names
        return {'role': 'assistant', 'tool_calls': [{
            'index': 0, 'id': 'native-rename', 'type': 'function',
            'function': {'name': 'bash',
                         'arguments': json.dumps({'command': shlex.join([
                             sys.executable, '-m', 'agent_comms.cli',
                             'rename-self', '--to', 'renamed-beta'])})},
        }]}, 'tool_calls'
    return {'role': 'assistant', 'content': f'NATIVE_RESPONSE_{number}'}, 'stop'


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    global provider_hold
    provider_hold = hold_next
    mode = app.selected_mode
    release.set(); hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    editor = view.prompt.prompt_text_area
    assert editor.agent_ready is agent.ready
    assert not editor.check_action('submit_now', ())
    assert view.queue_supported is agent.presentation.queue_supported
    view.prompt.text = 'SUBMISSION_SAVED_HISTORY'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    assert 'SUBMISSION_SAVED_HISTORY' in screen_paint(app)
    original_scope = agent.queue_attachment.scope
    assert original_scope.session_id == 'beta' and original_scope.admission.incarnation.name == 'beta'
    # Return through physical tabs before renaming this already attached owner.
    # No reconnect, refresh input or replacement load may repair the attachment.
    await channel_target('#team').open(NavigationContext(app, mode, agent.project_root_path,
        comms.messaging.user_identity(str(agent.project_root_path)).name))
    channel = app.selected_session
    await click_tab(app, pilot, mode)
    assert app.selected_session.conversation is view
    assert screen_paint(app).count('SUBMISSION_SAVED_HISTORY') == 1
    entered.clear(); release.clear()
    view.prompt.text = 'SUBMISSION_RENAME_WHILE_WARM'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, entered.is_set)
    assert agent.session_id == 'beta'
    assert comms.registry.canonical_name('beta') == 'renamed-beta'
    await until(pilot, lambda: view.turns.owner.busy)
    assert editor.check_action('submit_now', ())
    view.prompt.text = 'SUBMISSION_DEFERRED_AFTER_RENAME'
    await pilot.press('enter')
    await until(pilot, lambda: bool(agent.queue_attachment.projection.items))
    queued = agent.queue_attachment.projection.items[0]
    assert queued.text == 'SUBMISSION_DEFERRED_AFTER_RENAME'
    assert queued.text in view.query_one(QueueSummary).render().plain
    assert not view.prompt.text
    scope = agent.queue_attachment.scope
    assert scope.session_id == 'beta' and scope.admission.incarnation.name == 'renamed-beta'
    assert scope.relation(original_scope).current
    # Keep the actual queued turn open during another A/B/A reader return.
    view.prompt.text = 'SUBMISSION_UNSENT_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    await click_tab(app, pilot, channel.id)
    await click_tab(app, pilot, mode)
    assert view.prompt.prompt_text_area.document is document
    assert view.prompt.prompt_text_area.history is undo
    assert view.prompt.text == 'SUBMISSION_UNSENT_DRAFT'
    view.prompt.text = ''
    view.prompt.prompt_text_area.focus()
    assert await pilot.click(view.prompt.query_one(SendNow), offset=(1, 0))
    view.prompt.text = 'SUBMISSION_UNSENT_DRAFT'
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
    assert not editor.check_action('submit_now', ())
    log = agent.presentation.log_path.read_text()
    assert log.count("'kind': 'send_now'") == 1
    root = Path(os.environ['L0A_EVIDENCE'])
    (root / 'submission.svg').write_text(app.export_screenshot())
    (root / 'submission.json').write_text(json.dumps({
        'requests': len(requests), 'sessionId': agent.session_id,
        'owner': agent.queue_attachment.scope.admission.incarnation.name,
        'inputId': queued.input_id, 'inputState': disposition.public_status,
        'draftPreserved': view.prompt.text == 'SUBMISSION_UNSENT_DRAFT',
        'paint': screen_paint(app),
    }, indent=2))
    assert screen_paint(app).count('SUBMISSION_SAVED_HISTORY') <= 1
    print('PASS actual installed native rename, saved history, warm physical A/B/A, busy queue/start/input paint/first reply, no replay; four loopback requests', flush=True)

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance, provider_reply=reply,
                    provider_request_budget=4, expected_response_disconnects=frozenset({3})))
