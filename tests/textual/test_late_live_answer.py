"""Textual-facing: a live answer block that the conversation applies after the saved history already
covers it is drawn once, never twice, whichever way the saved history arrived."""

import asyncio
from dataclasses import replace
import os

import pytest
from agent_comms.acp_extension import (
    NativeOutputCommittedUpdate, NativeRoundCommittedUpdate, TranscriptSnapshotUpdate, TurnChangedUpdate,
)
from agent_comms.native_output import AssistantOutput, NativeOutputLocation
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.field_codec import FieldCodec, TurnId
from agent_comms.turn_lease import ActiveTurn, FinishedTurn, TurnState
from agent_comms.turn_phase import PublishingPhase

from toad.core.events import CommsUpdated, Update
from toad.transcript_publication import CommitPublication
from support.agents import deliver
from support.coordination import carrying
from support.journals import assistant_entry, write_journal

TOKEN = "LATE_LIVE_ANSWER"

FIRST_TURN = TurnId("f1e2d3c4b5a697881726354453627180")


def latest_assistant_commit(comms, name, journal):
    import json

    lines = journal.read_bytes().splitlines(keepends=True)
    header, entry = json.loads(lines[0]), json.loads(lines[-1])
    location = FieldCodec.decode(NativeOutputLocation, {
        "sessionId": header["id"], "sessionFile": str(journal),
        "sessionEntryId": entry["id"], "sessionEntryStart": sum(map(len, lines[:-1])),
        "sessionEntryEnd": sum(map(len, lines)), "output": {"kind": "assistant"}})
    return comms.transcripts.capture_native_output(name, location)


@pytest.mark.parametrize("arrival", ["read-in-flight", "commit", "queued-snapshot"])
async def test_late_live_answer_is_drawn_once(workspace, arrival):
    project = workspace.project
    comms = workspace.comms
    thread = workspace.thread("source")
    workspace.thread("peer")
    comms.messaging.send("peer", "source", "WIRE_NOTICE")
    held, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()
    read_release = asyncio.Event()
    pending = []
    async with workspace.app(size=(120, 35), resume="source") as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        await ui.until_shows("WIRE_NOTICE")
        reader = view.transcript.binding.reader
        read_snapshot = reader.snapshot
        copies_drawn = []
        duplicate_frame = []
        draw = app._display

        def recording_draw(screen, renderable):
            draw(screen, renderable)
            if renderable is not None and screen is app.screen:
                copies = ui.painted(view.window).count(TOKEN)
                copies_drawn.append(copies)
                if copies > 1 and not duplicate_frame:
                    duplicate_frame.append((
                        type(view.transcript.binding.history.state).__name__,
                        view.turns.owner.busy,
                        tuple((type(child).__name__, child.display, child.region,
                               ui.painted(child).count(TOKEN))
                              for child in view.contents.children),
                    ))

        app._display = recording_draw
        try:
            await view.transcript.suspend()
            dispatch = view._dispatch_message

            async def hold_the_live_answer(message):
                event = getattr(message, "event", None)
                if isinstance(event, Update) and event.text == TOKEN:
                    held.set()
                    await release.wait()
                    await dispatch(message)
                    applied.set()
                    return
                await dispatch(message)

            view._dispatch_message = hold_the_live_answer
            agent = ui.detached_agent("late-live")
            view.bind_agent(agent)
            turns = agent.presentation.managed_turns()
            turns.receive(TurnState(ActiveTurn(FIRST_TURN, os.getpid(), phase=PublishingPhase())))
            await ui.step()
            view.window.anchor()
            view.prompt.focus()

            if arrival == "read-in-flight":
                read_entered = asyncio.Event()
                async def held_read(*arguments, **options):
                    read_entered.set()
                    await read_release.wait()
                    return await read_snapshot(*arguments, **options)

                reader.snapshot = held_read
                view.transcript.dirty = view.transcript.commit_required = True
                pending.append(asyncio.create_task(view.transcript.publish(CommitPublication)))
                await asyncio.wait_for(read_entered.wait(), 5)

            answer = asyncio.create_task(deliver(agent, {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": TOKEN}}))
            pending.append(answer)
            await asyncio.wait_for(held.wait(), 5)
            # The session file and the end of the turn arrive while the live answer is still unapplied.
            saved = write_journal(project / "first-native.jsonl", assistant_entry(TOKEN, id="first-assistant"))
            comms.registry.declare(replace(thread, session_file=RegistrySessionLocation.from_path(str(saved), workspace.comms.root)))
            pending.append(asyncio.create_task(deliver(agent, carrying(TurnChangedUpdate(FinishedTurn(FIRST_TURN).state())))))
            await asyncio.sleep(.05)

            if arrival == "read-in-flight":
                read_release.set()
            else:
                view.transcript.dirty = view.transcript.commit_required = True
                if arrival == "commit":
                    pending.append(asyncio.create_task(view.transcript.publish(CommitPublication)))
                else:
                    page = await view.transcript.get_transcript_page()
                    agent.events.publish(CommsUpdated(
                        TranscriptSnapshotUpdate.capture(comms.transcripts, "source"), agent.session_id))

                    async def saved_history_shown():
                        async with asyncio.timeout(8):
                            while view.transcript.binding.history.page_source.through != page.after:
                                await asyncio.sleep(.02)

                    pending.append(asyncio.create_task(saved_history_shown()))
            await asyncio.sleep(.5)
            release.set()
            await asyncio.wait_for(asyncio.gather(*pending), 8)
            await asyncio.wait_for(applied.wait(), 5)
            await ui.until(lambda: ui.painted(view.window).count(TOKEN) == 1, seconds=5,
                           why="exactly one drawn copy of the answer")
            await ui.step(.5)
            assert ui.painted(view.window).count(TOKEN) == 1
            assert max(copies_drawn, default=0) <= 1, f"a frame drew the answer {max(copies_drawn)} times: {duplicate_frame!r}"
            assert agent.process.runner is None
        finally:
            release.set()
            read_release.set()
            reader.snapshot = read_snapshot
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


async def test_an_advancing_commit_retires_the_outgoing_body_and_its_tool_report(workspace):
    from acp.schema import ToolCall as AcpToolCall
    from agent_comms.sent_message import PublishedSentMessage
    from agent_comms.transcript_events import SentTranscript
    from toad.acp.status import ToolCallStatus
    from toad.tool_output import ToolOutput
    from toad.widgets.outgoing_message import OutgoingMessage
    from toad.widgets.tool_call import ToolCall

    source = workspace.thread("source")
    workspace.thread("peer")
    journal = write_journal(workspace.project / "source.jsonl",
                            assistant_entry("SAVED_NATIVE_PREFIX", id="prefix"))
    workspace.comms.registry.declare(replace(source, session_file=RegistrySessionLocation.from_path(str(journal), workspace.comms.root)))
    async with workspace.app(size=(120, 35), resume="source") as ui:
        view = ui.conversation
        await ui.until_shows("SAVED_NATIVE_PREFIX")
        await view.transcript.suspend()
        history = view.transcript.binding.history
        previous = history.outgoing_coverage
        record = workspace.comms.messaging.send("source", "peer", "ADVANCING_OUTGOING_BODY").message
        snapshot = TranscriptSnapshotUpdate.capture(workspace.comms.transcripts, "source")
        assert history.accepts_commit(snapshot.page.after), "This case must extend the existing source"
        report = SentTranscript.from_message(record)
        publication, = snapshot.identity.wire_frontier.resolve_sent((report,))
        assert isinstance(publication, PublishedSentMessage)
        status = ToolCallStatus.from_acp(AcpToolCall.model_validate({
            "toolCallId": "published-send", "title": "Send", "status": "completed",
            "content": [report.tool_content("published-send")],
        }))
        parts = ToolOutput.capture_projection(status, publication.scope)
        part, = parts
        tool = await view.post(ToolCall(status, output_parts=parts))
        tool.set_expanded(False)
        outgoing = await view.post(OutgoingMessage(part.message, row=part.row, binding=None, request=None))
        await ui.until_shows("ADVANCING_OUTGOING_BODY")
        assert publication.reference in tool.commit_claim.outgoing
        assert publication.reference not in previous
        view.window.anchor()
        view.prompt.focus()
        view.transcript.dirty = view.transcript.commit_required = True
        await view.transcript.publish(CommitPublication)
        await ui.until(lambda: not outgoing.is_attached and not tool.is_attached,
                       why="the saved outgoing body and its tool report handed off together")
        await ui.until(lambda: ui.painted(view.window).count("ADVANCING_OUTGOING_BODY") == 1,
                       why="one saved outgoing body after the live report retires")
        assert view.transcript.binding.history is history
        assert previous | {publication.reference} <= history.outgoing_coverage


@pytest.mark.parametrize('hidden_count', (1, 45), ids=('single-page', 'multi-page'))
async def test_returning_to_busy_tab_loads_the_saved_gap(workspace, hidden_count):
    import json

    journal = write_journal(workspace.project / "background.jsonl",
                            assistant_entry("SAVED_PREFIX", id="prefix"))
    thread = workspace.thread("background")
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root)))
    async with workspace.app(size=(140, 50), resume="background") as ui:
        await ui.until_shows("SAVED_PREFIX")
        view, tab = ui.conversation, ui.selected_tab
        agent = ui.detached_agent("background-live")
        view.bind_agent(agent)
        turns = agent.presentation.managed_turns()
        turns.receive(TurnState(ActiveTurn(FIRST_TURN, os.getpid(), phase=PublishingPhase())))
        await deliver(agent, {"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "BEFORE_TAB_PARK"}})
        await ui.until_shows("BEFORE_TAB_PARK")
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry("BEFORE_TAB_PARK", id="before", parent="prefix")) + "\n")
        committed = latest_assistant_commit(workspace.comms, "background", journal)
        await deliver(agent, carrying(NativeOutputCommittedUpdate(committed, AssistantOutput())))
        await deliver(agent, carrying(NativeRoundCommittedUpdate(committed)))
        await ui.new_session()
        with journal.open("a") as output:
            for index in range(hidden_count):
                text = 'WHILE_TAB_HIDDEN' if index == hidden_count - 1 else f'HIDDEN_HISTORY_{index}'
                output.write(json.dumps(assistant_entry(text, id=f'hidden-{index}',
                    parent=f'hidden-{index - 1}' if index else 'before')) + '\n')
        hidden = latest_assistant_commit(workspace.comms, "background", journal)
        pending_page = workspace.comms.transcripts.capture_page_read(
            'background', after=view.transcript.binding.history.page_source.through).read()
        assert pending_page.has_newer == (hidden_count > 20)
        if pending_page.has_newer:
            assert pending_page.after.offset < hidden.page_bound.offset
        await deliver(agent, carrying(NativeOutputCommittedUpdate(hidden, AssistantOutput())))
        await deliver(agent, carrying(NativeRoundCommittedUpdate(hidden)))
        await ui.select_tab(tab)
        assert ui.conversation is view
        assert view.turns.owner.busy
        await ui.until_shows("WHILE_TAB_HIDDEN")
        await ui.until(lambda: view.transcript.binding.history.page_source.through.offset
                       == hidden.page_bound.offset,
                       why='the kept busy tab to reach the committed multi-page source')
        if hidden_count > 20:
            import re

            expected = set(range(hidden_count - 1))
            seen = set()
            view.window.focus(scroll_visible=False)
            for _ in range(30):
                seen.update(int(value) for value in re.findall(r"HIDDEN_HISTORY_(\d+)", ui.painted(view.window)))
                if seen == expected:
                    break
                await ui.press("pageup")
            assert seen == expected, sorted(expected - seen)
            view.jump_to_latest()
            await ui.until_shows("WHILE_TAB_HIDDEN")
        # Disk can be ahead of ACP ingress. A busy read must stop at the
        # applied round fence, even when all mounted blocks are already sealed.
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry("AFTER_TAB_RETURN", id="after",
                parent=f'hidden-{hidden_count - 1}')) + "\n")
        view.transcript.dirty = view.transcript.commit_required = True
        await view.transcript.publish(CommitPublication)
        assert "AFTER_TAB_RETURN" not in ui.painted(view.window)
        await deliver(agent, {"sessionUpdate": "agent_message_chunk",
                              "content": {"type": "text", "text": "AFTER_TAB_RETURN"}})
        await ui.until_shows("AFTER_TAB_RETURN")
        after = latest_assistant_commit(workspace.comms, "background", journal)
        await deliver(agent, carrying(NativeOutputCommittedUpdate(after, AssistantOutput())))
        await deliver(agent, carrying(NativeRoundCommittedUpdate(after)))
        await ui.until(lambda: ui.painted(view.window).count("AFTER_TAB_RETURN") == 1
                       and view.transcript.binding.history.page_source.through.offset == after.page_bound.offset,
                       why="the applied saved row to replace its live body once")
