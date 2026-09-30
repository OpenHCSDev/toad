"""Production fork -> immediate first Toad open, without owner stop/start."""
import asyncio
import json
import os
from pathlib import Path
import psutil
from agent_comms.child_process import ProcessIdentity
from agent_comms.runtime import socket_path
from importlib.resources import files
from l0a_native_installed_pilot import main, until, response_painted
from runtime_fixture import ToadApp
from toad import messages
from toad.widgets.conversation import Conversation
from toad.navigation_preparation import ThreadNavigationRequest


async def dialog_content_only():
    """Actual installed dialog paste, with no fork, owner or provider start."""
    from textual import events
    from textual.widgets import Input, TextArea
    from agent_comms.threads import Thread
    from agent_comms.field_codec import FieldCodec
    from runtime_fixture import private_native_wire
    from toad.widgets.comms_fork_dialog import ForkDialog
    evidence = Path(os.environ['FORK_DIALOG_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=False)
    project = evidence / 'project'
    project.mkdir()
    comms = private_native_wire(evidence / 'wire')
    parent = Thread('fork-source', frozenset({'team', 'keep'}), str(project))
    comms.registry.declare(parent)
    results = []
    task = '  First acceptance instruction.\n\n    Second instruction must survive the paste.\n'
    app = InstalledApp(project_dir=str(project))
    async with app.run_test(size=(100, 38)) as pilot:
        await app.selected_session.wait_content_ready()
        app.push_screen(ForkDialog(parent), results.append)
        await until(pilot, lambda: isinstance(app.screen, ForkDialog))
        dialog = app.screen
        await until(pilot, lambda: dialog.query_one_optional('#fork-tags', Input) is not None)
        assert dialog.query_one('#fork-tags', Input).value == 'keep, team'
        dialog.query_one('#fork-name', Input).value = 'fork-child'
        editor = dialog.query_one('#fork-task')
        assert await pilot.click(editor)
        app.post_message(events.Paste(task))
        await pilot.pause()
        app.save_screenshot(str(evidence / 'pasted-task.svg'))
        assert await pilot.click('#fork-create')
        await until(pilot, lambda: bool(results))
        spec = results[0]
        (evidence / 'dialog-content.json').write_text(json.dumps({
            'expected_task': task, 'actual_spec': FieldCodec.encode(spec),
            'provider_calls': 0, 'owner_starts': 0,
        }, indent=2)+'\n')
        assert spec.name == 'fork-child' and spec.tags == parent.tags
        assert spec.task == task, (spec.task, task)
        assert app._exception is None
    (evidence / 'complete.txt').write_text('PASS: native dialog paste preserves full task text\n')


class InstalledApp(ToadApp):
    CSS_PATH = files('toad').joinpath('toad.tcss')


async def open_fork_dialog(app, pilot, comms, release, hold_next):
    """The existing parent response and actual sidebar/context-menu entry."""
    parent_view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: parent_view.agent_ready)
    await parent_view.submit_input(messages.UserInputSubmitted('FORK_PARENT_SEED'))
    await until(pilot, lambda: response_painted(app, parent_view, 'NATIVE_RESPONSE_1'))
    await until(pilot, lambda: not comms.registry.require('beta').executing)
    from runtime_fixture import wait_channel_roster
    from toad.widgets.comms_sidebar import CommsRow, ChannelGroup, CommsSidebar
    from toad.widgets.comms_menu import ContextMenuItem
    from toad.widgets.comms_fork_dialog import ForkDialog
    from toad.thread_actions import ForkAction
    from textual.widgets import Input, TextArea
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
    return parent_view, app.screen


async def task_admission(app, pilot, agent, comms, entered, release, hold_next, requests):
    """Optional text reaches the original native input; roster is a separate gate."""
    from textual import events
    from textual.widgets import Input, TextArea
    from agent_comms.transcript_events import UserTranscript, AssistantTranscript
    parent_view, dialog = await open_fork_dialog(app, pilot, comms, release, hold_next)
    task = '  First task instruction.\n\n    Preserve the second paragraph and its indentation.\n'
    name = 'multiline-task-fork'
    inherited = comms.registry.require('beta').tags
    assert dialog.query_one('#fork-tags', Input).value == ', '.join(sorted(inherited))
    dialog.query_one('#fork-name', Input).value = name
    editor = dialog.query_one('#fork-task', TextArea)
    assert await pilot.click(editor)
    app.post_message(events.Paste(task))
    await pilot.pause()
    assert editor.text == task
    evidence = Path(os.environ['L0A_EVIDENCE'])
    app.save_screenshot(str(evidence / 'multiline-native-task.svg'))
    await pilot.press('ctrl+enter')
    await until(pilot, lambda: name in comms.registry.all_threads())
    await until(pilot, lambda: len(requests) == 2, 30)
    await until(pilot, lambda: not comms.registry.require(name).executing, 30)
    child = comms.registry.require(name)
    page = comms.transcripts.thread_transcript_page(name)
    users = [event for event in page.events if isinstance(event, UserTranscript) and event.text == task]
    answers = [event for event in page.events if isinstance(event, AssistantTranscript)
               and event.text == 'NATIVE_RESPONSE_2']
    receipt = {'source_head': os.environ.get('TOAD_TEST_SOURCE_HEAD'),
               'native_dialog_ctrl_enter': True, 'original_task': task, 'child_task': child.task,
               'parent_tags': sorted(comms.registry.require('beta').tags), 'child_tags': sorted(child.tags),
               'native_task_inputs': [event.native_id for event in users],
               'native_child_answers': len(answers), 'source_file': page.after.session_file,
               'provider_requests': len(requests), 'paid_calls': 0,
               'roster_immediate_open_gate': 'separate; no forced roster refresh'}
    (evidence / 'native-task-admission.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert child.task == task and child.tags == inherited
    assert comms.registry.require('beta').tags == inherited
    assert len(users) == 1 and users[0].native_id is not None and len(answers) == 1, receipt
    assert len(requests) == 2 and app._exception is None


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    from textual.widgets import Input
    from runtime_fixture import wait_channel_roster
    from toad.widgets.comms_sidebar import CommsRow, ChannelGroup, CommsSidebar
    parent_view, dialog = await open_fork_dialog(app, pilot, comms, release, hold_next)
    entry = dialog.query_one("#fork-name", Input)
    assert await pilot.click(entry)
    entry.value = "immediate-fork"
    inherited_tags = comms.registry.require('beta').tags
    tags_editor = app.screen.query_one('#fork-tags', Input)
    assert tags_editor.value == ', '.join(sorted(inherited_tags))
    # Empty task is a ready child, not an automatic model input. Its tags are
    # editable declarations: retain the parent, add one and remove one here.
    tags_editor.value = 'fork-added'
    app.save_screenshot(str(Path(os.environ['L0A_EVIDENCE']) / 'empty-task-tags.svg'))
    async def hold_actual_startup():
        async with asyncio.timeout(20):
            while True:
                child = comms.registry.all_threads().get("immediate-fork")
                if child is not None and child.pid > 0:
                    process = psutil.Process(child.pid)
                    assert ProcessIdentity.capture(child.pid) == child.process_identity
                    assert Path(process.environ()["AGENT_COMMS_ROOT"]).resolve() == comms.root.resolve()
                    # The launcher publishes identity before its exec handshake
                    # completes. Suspending that launcher would deadlock ForkAction
                    # itself, before any physical opening could be exercised.
                    if process.cmdline()[1:3] == ["-m", "agent_comms.worker"]:
                        process.suspend()
                        return process
                await asyncio.sleep(.002)

    # Hold only this disposable test's actual newly spawned worker, before its
    # RPC socket exists. Native, ACP, registry and UI are unchanged real paths.
    # This guarantees an actual cold attach rather than a repaired warm fork.
    held_startup = asyncio.create_task(hold_actual_startup())
    try:
        assert await pilot.click('#fork-create')
        process = await held_startup
        project = parent_view.project_path
        await until(pilot, lambda: "immediate-fork" in comms.registry.all_threads())
        navigation = ThreadNavigationRequest(str(comms.root), 'immediate-fork', project, ()).read()
        child = navigation.thread
        startup_identity = child.process_identity
        endpoint = socket_path(comms.root, child.pid)
        cold_before_click = not endpoint.exists()
        print("ACTUAL_NEW_WORKER_BEFORE_SOCKET", cold_before_click, flush=True)
        if not cold_before_click:
            process.resume()
            raise AssertionError("Cold startup fixture missed the actual pre-socket interval")
        print('FIRST_VISIBLE_NAVIGATION', type(navigation).__name__, navigation.attachable,
              child.process_alive, bool(child.session_file), flush=True)
        if not navigation.attachable:
            raise AssertionError('Active immediate-fork startup routed to empty DirectTarget')
        user = comms.messaging.user_identity(str(project)).name
        previous_modes = tuple(app.tab_order.names)
        assert child.tags == frozenset({"fork-added"})
        assert comms.registry.require("beta").tags == inherited_tags
        try:
            sidebar = await wait_channel_roster(app, pilot, "#fork-added")
        except BaseException:
            sidebar = parent_view.screen.query_one(CommsSidebar)
            evidence = Path(os.environ['L0A_EVIDENCE'])
            evidence.joinpath('fork-roster-state.json').write_text(json.dumps({
                'screen': type(app.screen).__name__,
                'screen_frame_ready': parent_view.screen.frame_presentation.ready,
                'screen_frame_state': type(parent_view.screen.frame_presentation.state).__name__,
                'screen_is_current': parent_view.screen.is_current,
                'sidebar_attached': sidebar.is_attached, 'sidebar_display': sidebar.display,
                'observation_enabled': sidebar.observation.enabled,
                'accepts_publication': sidebar.accepts_publication(),
                'source_root': str(sidebar.observation.service.root),
                'navigation_ready': sidebar.navigation.ready.is_set(),
                'observation_pending': sidebar.observation.pending,
                'observation_lock': sidebar.observation.lock.locked(),
                'projection_lock': sidebar.projection.lock.locked(),
                'channel_rows': list(sidebar.projection.channels),
                'row_targets': [row.target_name for row in sidebar.query(CommsRow)],
                'original_registry_tags': {name: sorted(thread.tags) for name, thread in comms.registry.all_threads().items()},
                'provider_requests': len(requests),
            }, indent=2)+'\n')
            app.save_screenshot(str(evidence/'fork-roster-failure.svg'))
            raise
        print("FORK_MODAL_RETURN_FRAME", type(app.screen.frame_presentation.state).__name__,
              app.screen.frame_presentation.ready, app.screen.is_current, flush=True)
        group = sidebar.projection.channels['#fork-added'].query_ancestor(ChannelGroup)
        if not group.expanded:
            group.disclosure.scroll_visible(animate=False, immediate=True)
            await pilot.pause()
            assert await pilot.click(group.disclosure)
        await until(pilot, lambda: any(row.target_name == child.name for row in group.query(CommsRow)))
        child_row = next(row for row in group.query(CommsRow) if row.target_name == child.name)
        child_row.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(child_row)
        await until(pilot, lambda: app.selected_session is not parent_view.screen)
        print('PRODUCTION_FORK_RETURNED', flush=True)
        await app.selected_session.wait_content_ready()
        view = app.selected_session.query_one(Conversation)
        await until(pilot, lambda: view.agent is not None)
        try:
            await until(pilot, lambda: view.agent.presentation.log_path.exists()
                        and "session/load" in view.agent.presentation.log_path.read_text(), 10)
            print("PHYSICAL_OPEN_LOAD_SENT_BEFORE_SOCKET", not endpoint.exists(), flush=True)
            assert not endpoint.exists()
            # Exercise the historical five-second unsent-connect expiry with
            # the same actual owner held alive, rather than a quick warm attach.
            await asyncio.sleep(5.4)
            assert ProcessIdentity.capture(process.pid) == startup_identity
            assert comms.registry.require(child.name).process_identity == startup_identity
            assert not endpoint.exists()
            assert not view.agent.session.settled.is_set()
            print("ACTUAL_ATTACHMENT_PENDING_AFTER_OLD_FIVE_SECOND_EXPIRY", flush=True)
        finally:
            process.resume()
        await until(pilot, lambda: view.agent.session.settled.is_set(), 30)
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
        evidence = Path(os.environ["L0A_EVIDENCE"])
        (evidence / 'immediate-open.svg').write_text(app.export_screenshot())
        print('FIRST_FORK_INHERITED_HISTORY_PAINTED', flush=True)
        await until(pilot, lambda: not comms.registry.require(child.name).executing, 30)
        assert len(requests) == 1, 'An empty fork task must not make an automatic provider request'
        view.prompt.text = 'FIRST_FORK_NEW_INPUT'
        view.prompt.prompt_text_area.focus()
        await pilot.press('enter')
        await until(pilot, lambda: len(requests) == 2, 30)
        await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_2'), 30)
        from agent_comms.transcript_events import UserTranscript
        page = comms.transcripts.thread_transcript(child.name)
        assert sum(isinstance(event, UserTranscript) and event.text == 'FIRST_FORK_NEW_INPUT'
                   for event in page) == 1
        assert app.selected_mode == mode
        assert app.session_tracker.get_session(mode) is details and view.agent is attached_agent
        assert tuple(app.tab_order.names) == (*previous_modes, mode)
        assert comms.registry.require(child.name).process_identity == startup_identity
        assert ProcessIdentity.capture(process.pid) == startup_identity
        print('FIRST_FORK_PROMPT_AND_ANSWER_PAINTED_ONCE_SAME_LOGICAL_TAB', flush=True)
        (evidence / "fresh-fork.json").write_text(json.dumps({
            "source_head": os.environ.get("TOAD_TEST_SOURCE_HEAD"),
            "actual_canonical_fork": True, "physical_open_before_rpc_socket": cold_before_click,
            "empty_task": True, "automatic_child_provider_requests": 0,
            "inherited_tags_in_dialog": sorted(inherited_tags),
            "parent_tags_after_fork": sorted(comms.registry.require('beta').tags),
            "child_tags": sorted(child.tags), "physical_added_channel_disclosure": True,
            "pending_after_old_five_second_expiry": True,
            "same_owner_process_through_first_reply": True,
            "first_new_message_physical_enter": True,
            "new_child_response_painted_once": True, "one_logical_tab": True,
            "title_without_at_placeholder": details.title, "provider_inputs": len(requests),
        }, indent=2)+"\n")
    finally:
        if not held_startup.done():
            held_startup.cancel()
        result, = await asyncio.gather(held_startup, return_exceptions=True)
        if isinstance(result, psutil.Process):
            try:
                result.resume()
            except psutil.NoSuchProcess:
                pass



if __name__ == '__main__':
    if os.environ.get('FORK_DIALOG_EVIDENCE'):
        asyncio.run(dialog_content_only())
    else:
        asyncio.run(main(app_type=InstalledApp,
                         acceptance=task_admission if os.environ.get('FORK_NATIVE_TASK') else acceptance,
                         provider_request_budget=2,
                         fixture_stage=Path(os.environ['FORK_FIXTURE_STAGE'])))
