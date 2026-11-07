"""Textual-facing: a new conversation entry fades in as it appears, whether it first shows as a live
block or as a saved row, and a commit that replaces live blocks still fades the rows they never showed."""

from dataclasses import replace
import json
import os

from agent_comms.acp_extension import TurnChangedUpdate
from agent_comms.child_process import ProcessIdentity
from agent_comms.nominal.field_codec import TurnId
from agent_comms.turn_lease import ActiveTurn, FinishedTurn, TurnState
from agent_comms.turn_phase import PublishingPhase
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.fresh_private_session import create_fresh_private_session
from support.agents import deliver
from support.coordination import carrying, coordination_fact
from support.textual_steps import tool_status
from toad.frame_presentation import ARRIVAL, EFFECT_UNSTARTED
from toad.widgets.agent_response import AgentResponse
from toad.widgets.tool_call import ToolCall
from toad.widgets.transcript_history import TranscriptHistory

ANSWER, PEER = "LIVE_ANSWER_ROW", "PEER_SAVED_ROW"

FIRST_TURN = TurnId("f1e2d3c4b5a697881726354453627180")


async def test_every_live_conversation_block_runs_the_arrival_cascade_on_mount(workspace):
    """A live block runs the same cascade saved rows run, not a fade over its whole body."""
    async with workspace.app(size=(120, 40)) as ui:
        conversation = ui.conversation
        streamed = await conversation.post(AgentResponse(""))
        await streamed.append_fragment("Streamed agent text")
        tool = await conversation.post(ToolCall(tool_status({
            "toolCallId": "read-1", "title": "Read notes", "kind": "read", "status": "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": "notes"}}]})))
        await ui.step()
        blocks = (streamed, tool)
        assert [block.effect_phase(ARRIVAL) is EFFECT_UNSTARTED for block in blocks] == [False, False]
        # What it plays across is its own rows, so it can say which have not risen.
        assert [block.text_fades for block in blocks] == [(ARRIVAL,), (ARRIVAL,)]
        assert all(sum(block.cascade_runs()) > 0 for block in blocks), (
            f"a live block reporting no rows holds none back: "
            f"{[tuple(block.cascade_runs()) for block in blocks]}")


async def test_a_commit_retiring_a_live_block_still_fades_another_senders_row(workspace):
    project = workspace.project
    comms = workspace.comms
    saved = create_fresh_private_session(project / "sessions", worktree=project).path
    prompt = saved.read_text() + json.dumps({"type": "message", "id": "first-user",
        "timestamp": "2026-10-22T00:00:00Z", "message": {
        "role": "user", "content": [{"type": "text", "text": "ASK_ROW"}]}}) + "\n"
    saved.write_text(prompt)
    thread = comms.registry.declare(replace(workspace.thread("source"), session_file=RegistrySessionLocation.from_path(str(saved), workspace.comms.root)))
    workspace.thread("peer")
    comms.messaging.send("peer", "source", "EARLIER_NOTICE")
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent("arrival-fade")
        view.bind_agent(agent)
        coordination = replace(
            coordination_fact(workspace.comms, thread.name, owner=ProcessIdentity.capture(os.getpid()),
                              worktree=project, model="test-model"),
            thread=thread.incarnation)
        await deliver(agent, carrying(coordination))
        agent.presentation.managed_turns().receive(
            TurnState(ActiveTurn(FIRST_TURN, os.getpid(), phase=PublishingPhase())))
        # The saved history the commit grows: the earlier notice, read once the view binds its thread.
        await ui.until(lambda: "EARLIER_NOTICE" in ui.painted(view.window), why="the saved history")
        history = view.contents.query_one(TranscriptHistory)
        # A pager's cascade starts when rows arrive into it, not when it mounts with saved rows.
        assert history.effect_phase(ARRIVAL) is EFFECT_UNSTARTED
        view.window.anchor()
        await deliver(agent, {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ANSWER}})
        await ui.until(lambda: ANSWER in ui.painted(view.window), why="the live answer")
        live = view.contents.query_one(AgentResponse)
        # Every frame published across the commit, as the terminal received it.
        screen = ui.app.screen
        published = screen._on_frame_published
        frames: list[str] = []

        def recording() -> None:
            published()
            frames.append(ui.painted(view.window))

        screen._on_frame_published = recording
        # The answer is saved and the turn ends; another sender's message lands in the same append.
        saved.write_text(prompt + json.dumps({"type": "message", "id": "first-assistant",
            "parentId": "first-user", "timestamp": "2026-10-22T00:00:01Z", "message": {
            "role": "assistant", "content": [{"type": "text", "text": ANSWER}]}}) + "\n")
        comms.messaging.send("peer", "source", PEER)
        await deliver(agent, carrying(TurnChangedUpdate(FinishedTurn(FIRST_TURN).state())))
        view.transcript.require_commit()

        def rows(arriving: bool) -> str:
            return " ".join(event.text for page in history.pages for fragment in page.prepared.fragments_in_range
                            if not arriving or fragment.key in page.arrivals for event in fragment.events)

        # The commit is published once its saved rows replace the live block they cover.
        await ui.until(lambda: PEER in rows(arriving=False) and not live.display, why="the commit's saved rows")
        assert PEER in rows(arriving=True)
        assert ANSWER not in rows(arriving=True)
        await ui.until(lambda: any(PEER in frame for frame in frames), why="a published frame with the saved rows")
        screen._on_frame_published = published
        # The live block leaves in the frame that draws its saved rows: no frame shows both, or neither.
        assert [frame.count(ANSWER) for frame in frames] == [1] * len(frames)


def test_a_burst_comes_in_row_after_row_and_ends_whole():
    early = ARRIVAL.span / 2
    first, last = ARRIVAL.at(early, 0.0), ARRIVAL.at(early, 1.0)
    # The first row is already rising while the last has not started: it is still the background.
    assert first.amount > 0 and last.amount == 0
    assert ARRIVAL.at(ARRIVAL.duration, 1.0) == ARRIVAL.final


def test_a_following_reader_stops_above_the_rows_still_to_rise():
    # Five rows: at the start four wait below the window, and fewer as the front moves down.
    assert ARRIVAL.unrisen(0.0, 5) == 4
    assert ARRIVAL.unrisen(ARRIVAL.span / 2, 5) == 4
    assert ARRIVAL.unrisen(0.0, 1) == 0


def test_the_reveal_and_the_fade_run_on_one_clock():
    """The reveal that moves a following tail ends exactly when the fade it follows ends.

    Reading the front off the start of each row instead let the tail reach the bottom at
    `span`, while the paint kept fading until `span + fade.duration`: the scroll finished
    early and the rows under it went on rising. One front, one clock.
    """
    assert ARRIVAL.unrisen(ARRIVAL.span, 5) > 0, "rows still mid-fade have not risen"
    assert ARRIVAL.unrisen(ARRIVAL.duration, 5) == 0
    assert ARRIVAL.at(ARRIVAL.duration, 1.0) == ARRIVAL.final
    assert ARRIVAL.front(ARRIVAL.duration) == 1.0
    assert ARRIVAL.front(0.0) == 0.0
