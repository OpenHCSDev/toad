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
        await pilot.press("enter")
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
        sidebar = await wait_channel_roster(app, pilot, "#team")
        print("FORK_MODAL_RETURN_FRAME", type(app.screen.frame_presentation.state).__name__,
              app.screen.frame_presentation.ready, app.screen.is_current, flush=True)
        sidebar.observation.refresh()
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
        view.prompt.text = 'FIRST_FORK_NEW_INPUT'
        view.prompt.prompt_text_area.focus()
        await pilot.press('enter')
        await until(pilot, lambda: len(requests) >= 3, 30)
        await until(pilot, lambda: response_painted(app, view, 'NATIVE_RESPONSE_3'), 30)
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
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
