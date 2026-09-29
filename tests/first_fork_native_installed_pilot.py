"""Production fork -> immediate first Toad open, without owner stop/start."""
import asyncio
from importlib.resources import files
from agent_comms.thread_management import ForkSpec
from toad.navigation_target import ThreadTarget
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.conversation import Conversation
from toad.navigation_preparation import ThreadNavigationRequest


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    parent_view = app.screen.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: parent_view.agent_ready)
    await parent_view.submit_input(messages.UserInputSubmitted('FORK_PARENT_SEED'))
    await until(pilot, lambda: response_painted(app, parent_view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    fork = asyncio.create_task(asyncio.to_thread(comms.threads.fork, ForkSpec(
        'first-fork', 'beta', 'Reply briefly to this isolated first fork test.',
        frozenset({'team'}))))
    project = parent_view.project_path
    async with asyncio.timeout(30):
        while 'first-fork' not in comms.registry.all_threads():
            await asyncio.sleep(0)
    navigation = ThreadNavigationRequest(str(comms.root), 'first-fork', project, ()).read()
    child = navigation.thread
    print('FIRST_VISIBLE_NAVIGATION', navigation.active, navigation.resumable,
          child.process_alive, bool(child.session_file), fork.done(), flush=True)
    if not navigation.resumable:
        await fork
        raise AssertionError('Active first-fork startup routed to empty DirectTarget')
    user = comms.messaging.user_identity(str(project)).name
    await app.open_comms_session(owner_mode=app.current_mode, project_path=project,
        me=user, target=ThreadTarget(child.name))
    await fork
    print('PRODUCTION_FORK_RETURNED', flush=True)
    await app.screen.wait_content_ready()
    view = app.screen.query_one(Conversation)
    await until(pilot, lambda: view.agent is not None)
    await until(pilot, lambda: view.agent.session_ready_event.is_set(), 30)
    print('FIRST_OPEN_PHASE', view.agent.ready, view.agent_ready,
          repr(view.agent_title), len(view.contents.children), flush=True)
    await until(pilot, lambda: view.agent_ready, 30)
    assert view.agent.ready and view.agent_ready
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    details = app.session_tracker.get_session(app.current_mode)
    await until(pilot, lambda: details.title == child.name)
    assert view.agent.session_id == child.name
    assert not details.title.startswith('@')
    print('FIRST_FORK_INITIALIZED_TITLE', details.title, details.state, flush=True)
    from pathlib import Path
    Path('evidence/first-fork/first-open.svg').write_text(app.export_screenshot())
    print('FIRST_FORK_INHERITED_HISTORY_PAINTED', flush=True)
    await until(pilot, lambda: not comms.registry.require(child.name).executing, 30)
    import os
    if os.environ.get('FIRST_FORK_ATTACH_ONLY') == '1':
        print('FIRST_FORK_FIRST_INPUT_PENDING_CORE338', flush=True)
        return
    await view.submit_input(messages.UserInputSubmitted('FIRST_FORK_NEW_INPUT'))
    await until(pilot, lambda: len(requests) >= 3, 30)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_3'), 30)
    print('FIRST_FORK_PROMPT_AND_ANSWER_PAINTED', flush=True)


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
