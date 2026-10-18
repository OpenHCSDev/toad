"""Textual-facing: a new conversation entry fades in as it appears, whether it first shows as a live
block or as a saved row, and a commit that replaces live blocks still fades the rows they never showed."""

from dataclasses import replace
import json
import os

from agent_comms.acp_extension import CoordinationChangedUpdate, TurnChangedUpdate, encode_updates
from agent_comms.context_reading import UnmeasuredContext
from agent_comms.turn_lease import ActiveTurn, TurnState
from agent_comms.turn_phase import PublishingPhase
from ui_theme.effects import NEW_TEXT

from support.agents import deliver, detached
from support.textual_steps import tool_status
from toad.frame_presentation import EFFECT_UNSTARTED
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall
from toad.widgets.transcript_history import TranscriptHistory

ANSWER, PEER = "LIVE_ANSWER_ROW", "PEER_SAVED_ROW"


async def test_every_live_conversation_block_runs_the_arrival_fade_on_mount(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        conversation = ui.conversation
        streamed = await conversation.post(AgentResponse(""))
        await streamed.append_fragment("Streamed agent text")
        tool = await conversation.post(ToolCall(tool_status({
            "toolCallId": "read-1", "title": "Read notes", "kind": "read", "status": "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": "notes"}}]})))
        await ui.step()
        assert [block.effect_phase(NEW_TEXT) is EFFECT_UNSTARTED for block in (streamed, tool)] == [False, False]


async def test_a_commit_retiring_a_live_block_still_fades_another_senders_row(workspace):
    project = workspace.project
    comms = workspace.comms
    comms.messaging.initialize_private_initial_protocol()
    thread = workspace.thread("source", running=True)
    workspace.thread("peer")
    comms.messaging.send_message("peer", "source", "EARLIER_NOTICE")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = detached(project, "arrival-fade", app=ui.app)
        view.set_reactive(type(view).agent, agent)
        view.bind_agent(agent)
        coordination = CoordinationChangedUpdate(
            thread=thread.incarnation, wire_root=str(workspace.roots.wire), owner_pid=os.getpid(),
            worktree=str(project), model="test-model", thinking_level=None, title=thread.name,
            context_usage=UnmeasuredContext())
        agent.coordination = coordination
        await deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(coordination)})
        agent.presentation.managed_turns().receive(
            TurnState(ActiveTurn("first-turn", os.getpid(), phase=PublishingPhase())))
        # The saved history the commit grows: the earlier notice, read once the view binds its thread.
        await ui.until(lambda: "EARLIER_NOTICE" in ui.painted(view.window), why="the saved history")
        history = view.contents.query_one(TranscriptHistory)
        view.window.anchor()
        await deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ANSWER}})
        await ui.until(lambda: ANSWER in ui.painted(view.window), why="the live answer")
        # The answer is saved and the turn ends; another sender's message lands in the same append.
        saved = project / "first-native.jsonl"
        saved.write_text(json.dumps({"type": "message", "id": "first-assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": ANSWER}]}}) + "\n")
        comms.registry.declare(replace(thread, session_file=str(saved)))
        comms.messaging.send_message("peer", "source", PEER)
        await deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
            "_meta": encode_updates(TurnChangedUpdate(TurnState(finished_turn_id="first-turn")))})
        view.transcript.require_commit()

        def arrived() -> str:
            return " ".join(event.text for page in history.pages
                            for fragment in page.prepared.fragments_in_range if id(fragment) in page.arrivals
                            for event in fragment.events)

        await ui.until(lambda: PEER in arrived(), why="the other sender's saved row to arrive")
        assert ANSWER not in arrived()
        assert ui.painted(view.window).count(ANSWER) == 1
