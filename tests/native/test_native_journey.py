"""Toad through Core's ACP server to a real native owner: queue, saved history, reattach, restart.

The model is the controlled loopback provider; everything else is the real path.
"""

from agent_comms.session_file import RegistrySessionLocation
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import psutil
from agent_comms.acp_extension import QueuePromptRequest
from agent_comms.cli_verbs.queue_restart import QueueRestartCliCommand
from agent_comms.cli_verbs.fork import ForkCliCommand
from agent_comms.cli_verbs.start import StartCliCommand
from agent_comms.input_disposition import InputDispositions
from agent_comms.pi_vocabulary import OffThinkingLevel
from agent_comms.threads import Thread

from support.native import native_session
from support.native_steps import channel_message_feedback, direct_reply_feedback
from support.textual_steps import request_target_command
from toad.agent import AgentBase
from toad.widgets.agent_response import AgentResponse
from toad.widgets.comms_sidebar import CommsRow, CommsSidebar
from toad.widgets.prompt import QueueSummary
from toad.widgets.transcript_history import TranscriptHistory


def answered(native, text):
    return text in native.ui.painted(native.ui.conversation.window)


async def send_first_input_and_hold_its_reply(native):
    ui, provider = native.ui, native.provider
    provider.hold_next_request()
    await ui.until_agent_ready()
    await ui.write_draft("FIRST_NATIVE_INPUT")
    await ui.press("enter")
    await ui.until(provider.entered.is_set, seconds=30, why="the first input at the provider")


async def queue_behind_the_held_turn(native):
    ui, agent = native.ui, native.agent
    await asyncio.wait_for(agent.send_prompt(
        "QUEUED_NATIVE_INPUT", request=QueuePromptRequest("QUEUED_NATIVE_INPUT", True)), 10)
    view = ui.conversation
    await ui.until(lambda: bool(view.submissions.queue_projection.items), seconds=20, why="the queued input")
    queued = [row.input_id for row in view.submissions.queue_projection.items]
    assert len(queued) == 1
    assert "QUEUED_NATIVE_INPUT" in view.query_one(QueueSummary).render().plain
    return queued[0]


async def finish_both_turns(native):
    ui, agent = native.ui, native.agent
    native.provider.release()
    await ui.until(lambda: agent.presentation.prompt_in_flight == 0, seconds=25, why="the prompt to finish")
    await ui.until(lambda: not native.executing, seconds=20, why="the owner to finish its turns")
    await ui.step()
    assert len(native.provider.requests) >= 2, "The queued input never reached the provider"
    assert not ui.conversation.submissions.queue_projection.items
    await ui.until(lambda: answered(native, "NATIVE_RESPONSE_2"), seconds=20, why="the second answer on screen")


async def test_owner_is_attached_and_navigable(workspace, native_package):
    from toad.navigation_preparation import ThreadNavigationRequest

    async with native_session(workspace) as native:
        owner = native.comms.registry.require("beta")
        assert owner.process_identity is not None and owner.process_alive
        navigation = await asyncio.to_thread(
            ThreadNavigationRequest(native.comms, "beta", native.project, ()).read)
        assert navigation.attachable and navigation.thread.process_alive


async def test_busy_owner_is_shown_busy_in_the_sidebar_at_any_width(workspace, native_package):
    async with native_session(workspace) as native:
        ui = native.ui
        app, _pilot = ui.textual
        await send_first_input_and_hold_its_reply(native)
        sidebar = app.screen.query_one(CommsSidebar)

        def beta_row():
            return next((row for row in sidebar.query(CommsRow) if row.target_name == "beta"), None)

        await ui.until(lambda: beta_row() is not None and beta_row().has_class("-busy"), seconds=20,
                       why="the busy owner's sidebar row")
        for width in (96, 120):
            await ui.resize(width, 44)
            await ui.until(lambda: beta_row() is not None and beta_row().region.height == 2,
                           why="the two-row sidebar entry after resize")
            row = beta_row()
            assert row.has_class("-busy"), (row.render(), row.region)
            assert "provider/" not in row.render().plain
        native.provider.release()
        await ui.until(lambda: not native.executing, seconds=20, why="the owner to finish")


async def test_input_queued_behind_a_running_turn_is_consumed_and_saved(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, comms = native.ui, native.agent, native.comms
        view = ui.conversation
        await send_first_input_and_hold_its_reply(native)
        await ui.write_draft("unsent local draft")
        queued = await queue_behind_the_held_turn(native)
        await finish_both_turns(native)
        assert ui.draft() == "unsent local draft"

        # The live answer becomes saved history read from the native session file.
        await ui.until(lambda: view.turns.managed_id is None, seconds=20, why="the turn to end")
        await ui.until(lambda: all(history.checkpoint_available
                                   for history in view.contents.query(TranscriptHistory)), seconds=20,
                       why="saved history to be available")
        view.window.anchor()
        view.transcript.require_checkpoint()
        await ui.until(lambda: not view.transcript.dirty, seconds=20, why="the saved history to replace live blocks")
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_2"), seconds=20, why="the answer from saved history")
        assert view.contents.query(TranscriptHistory)
        assert not any(isinstance(child, AgentResponse) for child in view.contents.children)
        assert view.transcript.displayed_cursor is not None

        native_rows = [json.loads(line) for line in
                       Path(comms.registry.require("beta").runtime.path).read_text().splitlines()]
        disposition = InputDispositions(comms.root / InputDispositions.filename).read().rows["acp:" + queued]
        assert any(row.get("message", {}).get("inputId") == disposition.native_id for row in native_rows)
        assert not disposition.unresolved

        # A second ACP attachment to the same owner shows the same history and asks the model nothing.
        asked = len(native.provider.requests)
        owner_process = comms.registry.require("beta").process_identity
        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        assert agent.session.connected
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_2"), seconds=20, why="history after reattaching")
        assert comms.registry.require("beta").process_identity == owner_process
        assert len(native.provider.requests) == asked
        await ui.until(lambda: view.submissions.queue_projection.status == "available", seconds=20,
                       why="the queue view after reattaching")
        assert not view.submissions.queue_projection.items


async def test_input_queued_while_the_tab_is_hidden_is_shown_on_return(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent = native.ui, native.agent
        owner_tab = ui.selected_tab
        await send_first_input_and_hold_its_reply(native)
        await ui.write_draft("unsent local draft")
        process, queue = agent.process.process, agent.queue_attachment
        await ui.new_session()
        assert agent.process.process is process and process.returncode is None
        await asyncio.wait_for(agent.send_prompt(
            "QUEUED_NATIVE_INPUT", request=QueuePromptRequest("QUEUED_NATIVE_INPUT", True)), 10)
        await ui.until(lambda: bool(agent.queue_attachment.projection.items), seconds=20, why="the queued input")
        await ui.select_tab(owner_tab)
        view = ui.conversation
        assert view.agent_binding is agent
        await ui.until(lambda: view.turns.managed_id == agent.current_turn.managed_id, seconds=20,
                       why="the running turn on return")
        await ui.until(lambda: view.agent_binding.configuration.model.selected is not None, seconds=20,
                       why="the model selection")
        assert view.agent_binding.configuration.model.current == "selected-offline/fixture"
        assert view.turns.owner.busy
        assert agent.queue_attachment is queue
        assert agent.process.process is process and process.returncode is None
        await ui.until(lambda: bool(view.submissions.queue_projection.items), seconds=20,
                       why="the queued input in the returned view")
        assert "QUEUED_NATIVE_INPUT" in view.query_one(QueueSummary).render().plain
        assert ui.draft() == "unsent local draft"
        await finish_both_turns(native)
        assert ui.draft() == "unsent local draft"


async def test_fork_opens_saved_history_and_answers_a_fresh_direct_message(workspace, native_package):
    async with native_session(workspace) as native:
        ui, comms = native.ui, native.comms
        app, _pilot = ui.textual
        parent_tab = ui.selected_tab
        await ui.until_agent_ready()
        await ui.write_draft("SAVED_PARENT_INPUT")
        await ui.press("enter")
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_1"), seconds=30,
                       why="the parent's saved answer")
        await ui.until(lambda: not native.executing, seconds=20, why="the parent turn to finish")
        parent = comms.registry.require(native.thread)
        source = Path(parent.runtime.path)
        original = source.read_bytes()
        result = await asyncio.to_thread(ForkCliCommand(
            name="fork", parent=parent.name, project=str(native.project),
            model=parent.model, thinking_level=parent.thinking_level,
        ).apply, comms)
        assert result.created == "fork"
        child_tab = await app.thread_navigation.open(
            owner_mode=parent_tab, project_path=native.project, target="fork")
        assert child_tab != parent_tab and ui.selected_tab == child_tab
        await ui.until_agent_ready()
        view = ui.conversation
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=20,
                       why="the inherited answer in the newly opened fork")
        child = replace(native, agent=view.agent_binding, thread="fork")
        await direct_reply_feedback(child, child_tab,
                                    body="FIRST_DIRECT_MESSAGE_TO_FORK")
        await ui.select_tab(child_tab)
        assert ui.conversation is view and view.agent_binding is child.agent
        await ui.until(lambda: "NATIVE_RESPONSE_2" in ui.painted(view.window), seconds=20,
                       why="the fork's first reply on tab return")
        assert len(native.provider.requests) == 2
        assert source.read_bytes() == original


async def test_channel_message_the_thread_declines_is_marked_checked(workspace, native_package):
    async with native_session(workspace) as native:
        await channel_message_feedback(native, native.ui.selected_tab)
        assert len(native.provider.requests) == 1, native.provider.requests


async def test_stopped_owner_restarts_without_replaying_and_then_idles(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, comms, provider = native.ui, native.agent, native.comms, native.provider
        app, _pilot = ui.textual
        owner_tab = ui.selected_tab
        await ui.until_agent_ready()
        await ui.write_draft("FIRST_NATIVE_INPUT")
        await ui.press("enter")
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_1"), seconds=30, why="the first answer")
        await ui.until(lambda: not native.executing, seconds=20, why="the owner to finish")
        first_owner = comms.registry.require("beta").process_identity

        acp_process = agent.process.process
        await agent.stop()
        assert acp_process.returncode is not None
        assert not agent.permissions.pending
        await asyncio.to_thread(comms.owners.stop, "beta")
        assert not comms.registry.require("beta").process_alive
        request_target_command(app, StartCliCommand, "beta")
        await ui.until(lambda: "beta" not in app.thread_actions.pending, seconds=30, why="Start to finish")
        assert comms.registry.require("beta").process_alive, "Start did not launch the owner"

        asked = len(provider.requests)
        await ui.select_tab(owner_tab)
        assert ui.conversation.agent_binding is agent, "Returning to a session replaced its agent"
        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        assert agent.session.connected, "The restarted owner did not accept the session"
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_1"), seconds=20, why="saved history after restart")
        assert len(provider.requests) == asked, "Restart replayed a model input"
        restarted = comms.registry.require("beta").process_identity
        assert restarted is not None and restarted != first_owner
        await asyncio.wait_for(agent.send_prompt("AFTER_RESTART_NATIVE"), 20)
        await ui.until(lambda: not native.executing, seconds=20, why="the new turn to finish")
        assert len(provider.requests) == asked + 1

        # With no new input, an idle owner asks the model nothing and starts no turn.
        assert psutil.pid_exists(restarted.pid)
        asked = len(provider.requests)
        await ui.step(2)
        assert len(provider.requests) == asked
        assert not native.executing


async def test_queue_line_follows_the_owner_after_restart_process(workspace, native_package):
    async with native_session(workspace) as native:
        ui, agent, comms = native.ui, native.agent, native.comms
        app, _pilot = ui.textual
        view = ui.conversation
        await ui.until_agent_ready()
        await ui.until(lambda: view.submissions.queue_projection.status == "available", seconds=20,
                       why="the queue view before the restart")
        first_owner = comms.registry.require("beta").process_identity

        request_target_command(app, QueueRestartCliCommand, "beta")
        await ui.until(lambda: comms.registry.require("beta").process_identity not in (None, first_owner),
                       seconds=60, why="the queued restart to replace the idle owner")
        restarted = comms.registry.require("beta").process_identity

        def queue_of_the_new_owner():
            scope = agent.queue_attachment.scope
            return (view.submissions.queue_projection.status == "available"
                    and scope is not None and scope.owner == restarted)

        await ui.until(queue_of_the_new_owner, seconds=30, why="the queue view of the restarted owner")
        await ui.step()
        assert "Remote queue unavailable" not in view.query_one(QueueSummary).render().plain
        assert comms.registry.require("beta").process_identity == restarted


async def test_a_second_thread_opened_from_the_app_answers_its_first_message(workspace, native_package):
    from support.native import MODEL

    async def declare_second(comms, project, _provider):
        comms.registry.declare(Thread("gamma", frozenset({"team"}), str(project), model=MODEL, thinking_level=OffThinkingLevel))

    async with native_session(workspace, prepare=declare_second) as native:
        ui, provider = native.ui, native.provider
        app, _pilot = ui.textual
        owner_tab = ui.selected_tab
        await ui.until_agent_ready()
        opened = await app.thread_navigation.open(owner_mode=owner_tab, project_path=native.project, target="gamma")
        assert opened != owner_tab and ui.selected_tab == opened
        assert [tab.identity for tab in ui.tabs()] == [owner_tab, opened]
        view = ui.conversation
        await ui.until(lambda: isinstance(view.agent_binding, AgentBase)
                       and view.agent_binding is not native.agent, seconds=20,
                       why="the second thread's agent")
        await ui.until_agent_ready()
        await ui.write_draft("FIRST_MESSAGE_TO_GAMMA")
        await ui.press("enter")
        await ui.until(lambda: "NATIVE_RESPONSE_1" in ui.painted(view.window), seconds=40, why="the first answer")
        await ui.until(lambda: not native.comms.registry.require("gamma").executing, seconds=20, why="the turn to finish")
        assert len(provider.requests) == 1
        assert ui.painted(view.window).count("NATIVE_RESPONSE_1") == 1
        assert [tab.identity for tab in ui.tabs()] == [owner_tab, opened]
        await view.agent_binding.stop()
