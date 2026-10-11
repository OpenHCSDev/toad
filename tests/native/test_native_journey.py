"""Toad through Core's ACP server to a real native owner: queue, saved history, reattach, restart.

The model is the controlled loopback provider; everything else is the real path.
"""

import asyncio
import json
from pathlib import Path

import psutil
from agent_comms.acp_extension import QueuePromptRequest
from agent_comms.cli_commands import StartCliCommand
from agent_comms.input_disposition import InputDispositions

from support.native import ControlledProvider, native_session
from support.native_steps import channel_message_feedback, direct_reply_feedback
from support.textual_steps import request_target_command
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

    async with native_session(workspace, native_package) as native:
        owner = native.comms.registry.require("beta")
        assert owner.process_identity is not None and owner.process_alive
        navigation = await asyncio.to_thread(
            ThreadNavigationRequest(native.comms, "beta", native.project, ()).read)
        assert navigation.attachable and navigation.thread.process_alive


async def test_busy_owner_is_shown_busy_in_the_sidebar_at_any_width(workspace, native_package):
    async with native_session(workspace, native_package) as native:
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
    async with native_session(workspace, native_package) as native:
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
                       Path(comms.registry.require("beta").session_file).read_text().splitlines()]
        disposition = InputDispositions(comms.root / InputDispositions.filename).read().rows["acp:" + queued]
        assert any(row.get("message", {}).get("inputId") == disposition.native_id for row in native_rows)
        assert not disposition.unresolved

        # A second ACP attachment to the same owner shows the same history and asks the model nothing.
        asked = len(native.provider.requests)
        owner_process = comms.registry.require("beta").process_identity
        watcher = view._directory_watcher
        assert watcher is not None
        await agent.session.reconnect()
        await ui.until(agent.session.settled.is_set, seconds=30, why="the reconnect to settle")
        assert agent.session.connected
        await ui.until(lambda: answered(native, "NATIVE_RESPONSE_2"), seconds=20, why="history after reattaching")
        assert comms.registry.require("beta").process_identity == owner_process
        assert len(native.provider.requests) == asked
        await ui.until(lambda: view.submissions.queue_projection.status == "available", seconds=20,
                       why="the queue view after reattaching")
        assert not view.submissions.queue_projection.items
        await ui.step()
        assert view._directory_watcher is watcher


async def test_input_queued_while_the_tab_is_hidden_is_shown_on_return(workspace, native_package):
    async with native_session(workspace, native_package) as native:
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
        assert view.agent is agent
        await ui.until(lambda: view.turns.managed_id == agent.current_turn.managed_id, seconds=20,
                       why="the running turn on return")
        await ui.until(lambda: view.agent.configuration.model.selected is not None, seconds=20,
                       why="the model selection")
        assert view.agent.configuration.model.current == "selected-offline/fixture"
        assert view.busy_count == 1
        assert agent.queue_attachment is queue
        assert agent.process.process is process and process.returncode is None
        await ui.until(lambda: bool(view.submissions.queue_projection.items), seconds=20,
                       why="the queued input in the returned view")
        assert "QUEUED_NATIVE_INPUT" in view.query_one(QueueSummary).render().plain
        assert ui.draft() == "unsent local draft"
        await finish_both_turns(native)
        assert ui.draft() == "unsent local draft"


async def test_direct_message_is_answered_once_and_marked_responded(workspace, native_package):
    async with native_session(workspace, native_package) as native:
        await direct_reply_feedback(native, native.ui.selected_tab, hold=True)


async def test_channel_message_the_thread_declines_is_marked_checked(workspace, native_package):
    async with native_session(workspace, native_package) as native:
        await channel_message_feedback(native, native.ui.selected_tab)
        assert len(native.provider.requests) == 1, native.provider.requests


async def test_stopped_owner_restarts_without_replaying_and_then_idles(workspace, native_package):
    async with native_session(workspace, native_package) as native:
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
        assert ui.conversation.agent is agent, "Returning to a session replaced its agent"
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
