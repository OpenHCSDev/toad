"""Production fork -> immediate first Toad open, without owner stop/start."""
import asyncio
from importlib.resources import files
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.conversation import Conversation
from toad.navigation_preparation import ThreadNavigationRequest


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    parent_view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: parent_view.agent_ready)
    await parent_view.submit_input(messages.UserInputSubmitted('FORK_PARENT_SEED'))
    await until(pilot, lambda: response_painted(app, parent_view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    from runtime_fixture import wait_channel_roster
    from toad.widgets.comms_sidebar import CommsRow
    from toad.widgets.comms_menu import ContextMenuItem
    from toad.widgets.comms_fork_dialog import ForkDialog
    from toad.thread_actions import ForkAction
    from textual.widgets import Input
    sidebar = await wait_channel_roster(app, pilot, "#team")
    row = next(row for row in sidebar.query(CommsRow) if row.target_name == "beta")
    row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(row, button=3)
    await until(pilot, lambda: bool(app.screen.query(ContextMenuItem)))
    menu_item = next(item for item in app.screen.query(ContextMenuItem)
                     if item.action == ForkAction.declared_name)
    assert await pilot.click(menu_item)
    await until(pilot, lambda: isinstance(app.screen, ForkDialog))
    entry = app.screen.query_one(Input)
    assert await pilot.click(entry)
    entry.value = "immediate-fork Reply briefly to this isolated first fork test."
    await pilot.press("enter")
    project = parent_view.project_path
    await until(pilot, lambda: "immediate-fork" in comms.registry.all_threads())
    navigation = ThreadNavigationRequest(str(comms.root), 'immediate-fork', project, ()).read()
    child = navigation.thread
    print('FIRST_VISIBLE_NAVIGATION', type(navigation).__name__, navigation.attachable,
          child.process_alive, bool(child.session_file), flush=True)
    if not navigation.attachable:
        raise AssertionError('Active immediate-fork startup routed to empty DirectTarget')
    user = comms.messaging.user_identity(str(project)).name
    previous_modes = tuple(app.tab_order.names)
    sidebar = await wait_channel_roster(app, pilot, "#team")
    sidebar._refresh()
    await until(pilot, lambda: any(row.target_name == child.name for row in sidebar.query(CommsRow)))
    child_row = next(row for row in sidebar.query(CommsRow) if row.target_name == child.name)
    child_row.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    assert await pilot.click(child_row)
    await until(pilot, lambda: app.selected_session is not parent_view.screen)
    print('PRODUCTION_FORK_RETURNED', flush=True)
    await app.selected_session.wait_content_ready()
    view = app.selected_session.query_one(Conversation)
    await until(pilot, lambda: view.agent is not None)
    await until(pilot, lambda: view.agent.session_ready_event.is_set(), 30)
    print('FIRST_OPEN_PHASE', view.agent.ready, view.agent_ready,
          repr(view.agent_title), len(view.contents.children), flush=True)
    await until(pilot, lambda: view.agent_ready, 30)
    assert view.agent.ready and view.agent_ready
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_1'), 30)
    mode = app.selected_mode
    details = app.session_tracker.get_session(mode)
    assert tuple(app.tab_order.names) == (*previous_modes, mode)
    attached_agent = view.agent
    await until(pilot, lambda: details.title == child.name)
    assert view.agent.session_id == child.name
    assert not details.title.startswith('@')
    print('FIRST_FORK_INITIALIZED_TITLE', details.title, details.state, flush=True)
    from pathlib import Path
    Path('evidence/owner-startup/immediate-open.svg').write_text(app.export_screenshot())
    print('FIRST_FORK_INHERITED_HISTORY_PAINTED', flush=True)
    await until(pilot, lambda: not comms.registry.require(child.name).executing, 30)
    await view.submit_input(messages.UserInputSubmitted('FIRST_FORK_NEW_INPUT'))
    await until(pilot, lambda: len(requests) >= 3, 30)
    await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_3'), 30)
    from agent_comms.transcript_events import UserTranscript
    page = comms.transcripts.thread_transcript(child.name)
    assert sum(isinstance(event, UserTranscript) and event.text == 'FIRST_FORK_NEW_INPUT'
               for event in page) == 1
    assert app.selected_mode == mode
    assert app.session_tracker.get_session(mode) is details and view.agent is attached_agent
    assert tuple(app.tab_order.names) == (*previous_modes, mode)
    print('FIRST_FORK_PROMPT_AND_ANSWER_PAINTED_ONCE_SAME_LOGICAL_TAB', flush=True)


if __name__ == '__main__':
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
