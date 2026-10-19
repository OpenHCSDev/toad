"""Textual-facing: a live answer block that the conversation applies after the saved history already
covers it is drawn once, never twice, whichever way the saved history arrived."""

import asyncio
from dataclasses import replace
import json
import os

import pytest
from agent_comms.acp_extension import (
    CoordinationChangedUpdate, TranscriptSnapshotUpdate, TurnChangedUpdate, encode_updates,
)
from agent_comms.comms import Comms
from agent_comms.threads import Thread
from agent_comms.turn_lease import ActiveTurn, TurnState
from agent_comms.turn_phase import PublishingPhase

from toad.core.events import CommsUpdated, Update
from toad.transcript_publication import CheckpointPublication
from toad.widgets.transcript_history import TranscriptHistory

TOKEN = "LATE_LIVE_ANSWER"


@pytest.mark.parametrize("arrival", ["read-in-flight", "checkpoint", "snapshot", "queued-snapshot"])
async def test_late_live_answer_is_drawn_once(workspace, arrival):
    project = workspace.project
    comms = Comms(workspace.roots.wire)
    comms.messaging.initialize_private_initial_protocol()
    thread = comms.registry.declare(Thread("source", frozenset(), str(project)))
    comms.registry.declare(Thread("peer", frozenset(), str(project)))
    comms.messaging.send_message("peer", "source", "WIRE_NOTICE")
    first_page = comms.transcripts.thread_transcript_page("source")
    held, release, applied = asyncio.Event(), asyncio.Event(), asyncio.Event()
    read_release = asyncio.Event()
    pending = []
    async with workspace.app(size=(120, 35)) as ui:
        app, _pilot = ui.textual
        view = ui.conversation
        copies_drawn = []
        draw = app._display

        def recording_draw(screen, renderable):
            draw(screen, renderable)
            if renderable is not None and screen is app.screen:
                copies_drawn.append(ui.painted(view.window).count(TOKEN))

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
            view.set_reactive(type(view).agent, agent)
            view.bind_agent(agent)
            agent.coordination = CoordinationChangedUpdate(
                thread.incarnation, str(workspace.roots.wire), os.getpid(), str(project), None, None, thread.name, None)
            turns = agent.presentation.managed_turns()
            turns.receive(TurnState(ActiveTurn("first-turn", os.getpid(), phase=PublishingPhase())))
            view.set_reactive(type(view).agent_ready, False)
            history = TranscriptHistory(first_page)
            await view.contents.mount(history)
            await ui.step()
            view.set_reactive(type(view).agent_ready, True)
            history.loader = agent.get_transcript_page
            view.window.anchor()
            view.prompt.focus()

            if arrival == "read-in-flight":
                read_entered = asyncio.Event()
                read_page = agent.get_transcript_page

                async def held_read(*arguments, **options):
                    read_entered.set()
                    await read_release.wait()
                    return await read_page(*arguments, **options)

                agent.get_transcript_page = held_read
                view.transcript.dirty = view.transcript.checkpoint_required = True
                pending.append(asyncio.create_task(view.transcript.publish(CheckpointPublication)))
                await asyncio.wait_for(read_entered.wait(), 5)

            answer = asyncio.create_task(agent.updates.receive("late-live", {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": TOKEN}}))
            pending.append(answer)
            await asyncio.wait_for(held.wait(), 5)
            # The session file and the end of the turn arrive while the live answer is still unapplied.
            saved = project / "first-native.jsonl"
            saved.write_text(json.dumps({"type": "message", "id": "first-assistant", "message": {
                "role": "assistant", "content": [{"type": "text", "text": TOKEN}]}}) + "\n")
            comms.registry.declare(replace(thread, session_file=str(saved)))
            pending.append(asyncio.create_task(agent.updates.receive("late-live", {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ""},
                "_meta": encode_updates(TurnChangedUpdate(TurnState(finished_turn_id="first-turn")))})))
            await asyncio.sleep(.05)

            if arrival == "read-in-flight":
                read_release.set()
            else:
                view.transcript.dirty = view.transcript.checkpoint_required = True
                if arrival == "checkpoint":
                    pending.append(asyncio.create_task(view.transcript.publish(CheckpointPublication)))
                else:
                    page = await agent.get_transcript_page()
                    if arrival == "snapshot":
                        pending.append(asyncio.create_task(view.transcript.snapshot(page)))
                    else:
                        agent.events.publish(CommsUpdated(
                            TranscriptSnapshotUpdate.capture(comms.transcripts, "source"), agent.session_id))

                        async def saved_history_shown():
                            async with asyncio.timeout(8):
                                while not any(item.page_source.through == page.after
                                              for item in view.transcript.histories):
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
            assert max(copies_drawn, default=0) <= 1, f"a frame drew the answer {max(copies_drawn)} times"
            assert agent.process.runner is None
        finally:
            release.set()
            read_release.set()
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
