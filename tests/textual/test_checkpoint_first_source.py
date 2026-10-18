"""Textual-facing: a checkpoint of a session whose native source file appeared after the first history replaces that history and the covered live response in the window.

Textual owns mounting and removing the history and response widgets that the checkpoint replaces.
"""

import asyncio
from dataclasses import replace
import os

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.threads import Thread

from support import agents, journals
from toad.live_output import ResponseStream
from toad.transcript_publication import CheckpointPublication
from toad.widgets.agent_response import AgentResponse
from toad.widgets.transcript_history import TranscriptHistory


async def test_first_native_file_replaces_the_wire_history_and_the_covered_live_response(workspace):
    comms = workspace.comms
    thread = comms.registry.declare(Thread("source", frozenset(), str(workspace.project)))
    comms.registry.declare(Thread("peer", frozenset(), str(workspace.project)))
    notice = comms.messaging.send_message("peer", "source", "ORIGINAL_WIRE_NOTICE")
    old_page = comms.transcripts.thread_transcript_page("source")
    assert not old_page.after.session_file
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = agents.detached(workspace.project)
        ui.attach_agent(agent)
        agent.coordination = CoordinationChangedUpdate(
            thread.incarnation, str(workspace.roots.wire), os.getpid(), str(workspace.project),
            None, None, thread.name, None)
        view.set_reactive(type(view).agent_ready, False)
        old = TranscriptHistory(old_page)
        await view.contents.mount(old)
        await ui.until(lambda: old.is_mounted, why="the wire history")
        view.set_reactive(type(view).agent_ready, True)
        live = await view.output.append(ResponseStream(), "FIRST_SAVED_NATIVE_RESPONSE")
        await ui.step()
        source = journals.write_journal(
            workspace.project / "first-native.jsonl",
            journals.user_entry("FIRST_SAVED_NATIVE_USER", id="native-user-original"),
            journals.assistant_entry("FIRST_SAVED_NATIVE_RESPONSE", id="native-assistant-original",
                                     parent="native-user-original"))
        installed = comms.registry.declare(replace(thread, session_file=str(source)))
        assert installed.incarnation == thread.incarnation
        page = await agent.get_transcript_page()
        assert page.after.session_file != old_page.after.session_file
        assert not old.accepts_commit(page.after)
        view.window.anchor()
        view.prompt.focus()
        view.transcript.dirty = view.transcript.checkpoint_required = True
        publication = CheckpointPublication(view.transcript, view, view.window, view.contents)
        assert publication.admitted() and publication.native_current()
        task = asyncio.create_task(publication.publish())
        try:
            await ui.until(task.done, seconds=8, why="the checkpoint published")
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await ui.step()
        histories = view.transcript.histories
        replacement = histories[0]
        assert len(view.window.histories) == len(histories) == 1
        assert not old.is_attached and not live.is_attached
        assert not list(view.contents.query(AgentResponse)), "the covered live response is still mounted"
        await ui.until(lambda: ui.painted(view.window).count("FIRST_SAVED_NATIVE_RESPONSE") == 1,
                       why="the saved response drawn exactly once")
        assert replacement.page_source.through == page.after
        assert replacement.loader == agent.get_transcript_page
        assert replacement.covers_incoming(notice.seq)
