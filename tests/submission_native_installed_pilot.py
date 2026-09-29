"""Saved native reply -> physical ordinary/deferred/Send now -> retained source return."""
import asyncio
import os
from importlib.resources import files
from pathlib import Path
from agent_comms.input_disposition import InputDispositions
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad.navigation_target import channel_target, NavigationContext
from toad.widgets.prompt import QueueSummary

class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')

async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    mode = app.selected_mode
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    view.prompt.text = 'SUBMISSION_SAVED_HISTORY'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    await agent.reconnect()
    await until(pilot, lambda: view.agent_ready and response_painted(app, view, 'NATIVE_RESPONSE_1'))
    entered.clear(); release.clear(); hold_next.set()
    view.prompt.text = 'SUBMISSION_ORDINARY'
    view.prompt.prompt_text_area.focus()
    await pilot.press('enter')
    await until(pilot, entered.is_set)
    await until(pilot, lambda: view.turns.owner.busy)
    view.prompt.text = 'SUBMISSION_DEFERRED'
    await pilot.press('enter')
    await until(pilot, lambda: bool(view.queue_projection.items))
    queued = view.queue_projection.items[0]
    assert queued.text == 'SUBMISSION_DEFERRED'
    assert 'SUBMISSION_DEFERRED' in view.query_one(QueueSummary).render().plain
    assert not view.prompt.text
    await pilot.press('ctrl+y')
    await pilot.pause()
    release.set()
    await until(pilot, lambda: not comms.registry.require('beta').executing and len(requests) == 3, 30)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_3'))
    assert not view.queue_projection.items
    await until(pilot, lambda: not view.submissions.active and view.submissions.requested_queue is None)
    assert not view.submissions.active and view.submissions.requested_queue is None
    disposition = InputDispositions(comms.root / InputDispositions.filename).read().rows['acp:' + queued.input_id]
    assert not disposition.unresolved and disposition.native_id
    view.prompt.text = 'SUBMISSION_UNSENT_DRAFT'
    document = view.prompt.prompt_text_area.document
    undo = view.prompt.prompt_text_area.history
    await channel_target('#team').open(NavigationContext(app, mode, agent.project_root_path,
        comms.messaging.user_identity(str(agent.project_root_path)).name))
    await app.select_session(mode)
    returned = app.selected_session.conversation
    assert returned.agent is agent
    await until(pilot, lambda: response_painted(app, returned, 'NATIVE_RESPONSE_3'))
    assert returned.prompt.text == 'SUBMISSION_UNSENT_DRAFT'
    assert returned.prompt.prompt_text_area.document is document
    assert returned.prompt.prompt_text_area.history is undo
    assert len(requests) == 3
    delivery = await agent.controller.input_delivery(include_history=True)
    assert delivery['inputs'] == [], delivery
    assert await agent.get_goal_snapshot() == (None, None)
    assert agent.controller.prompt_in_flight == 0
    assert not agent.controller._deferred_submissions
    log = agent.presentation.log_path.read_text()
    assert log.count("'kind': 'send_now'") == 1, log
    root = Path(os.environ['L0A_EVIDENCE'])
    (root / 'submission.svg').write_text(app.export_screenshot())
    print('PASS physical ordinary/deferred/Send now, exact native queue consumption, retained reply/draft/Document/undo; three loopback requests', flush=True)

if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance, expected_response_disconnects=frozenset({2})))
