"""Textual-facing: a checkpoint of a session whose native source file appeared after the first history replaces that history and the covered live response in the window.

Textual owns mounting and removing the history and response widgets that the checkpoint replaces.
"""

from agent_comms.session_file import RegistrySessionLocation
import asyncio
from dataclasses import replace
import os

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.child_process import ProcessIdentity
from agent_comms.context_reading import UnmeasuredContext

from support import journals
from support.agents import deliver
from support.coordination import carrying
from toad.live_output import ResponseStream
from toad.transcript_publication import CommitPublication
from toad.widgets.agent_response import AgentResponse
from support.textual_steps import saved_history


async def test_first_native_file_replaces_the_wire_history_and_the_covered_live_response(workspace):
    comms = workspace.comms
    thread = workspace.thread("source")
    workspace.thread("peer")
    notice = comms.messaging.send("peer", "source", "ORIGINAL_WIRE_NOTICE").message
    old_page = comms.transcripts.capture_page_read("source").read()
    assert not old_page.after.session_file
    async with workspace.app(size=(120, 35)) as ui:
        view = ui.conversation
        agent = ui.detached_agent("checkpoint-first")
        ui.attach_agent(agent)
        agent.coordination = coordination = CoordinationChangedUpdate(
            thread=thread.incarnation, wire_root=str(workspace.roots.wire), owner=ProcessIdentity.capture(os.getpid()),
            worktree=str(workspace.project), model="test-model", thinking_level=None, title=thread.name,
            context_usage=UnmeasuredContext())
        await deliver(agent, carrying(coordination))
        agent.session.settled.clear()
        old = await saved_history(view, old_page, view.transcript.get_transcript_page)
        await view.contents.mount(old)
        await ui.until(lambda: old.is_mounted, why="the wire history")
        agent.session.settled.set()
        live = await view.output.append(ResponseStream(), "FIRST_SAVED_NATIVE_RESPONSE")
        await ui.step()
        source = journals.write_journal(
            workspace.project / "first-native.jsonl",
            journals.user_entry("FIRST_SAVED_NATIVE_USER", id="native-user-original"),
            journals.assistant_entry("FIRST_SAVED_NATIVE_RESPONSE", id="native-assistant-original",
                                     parent="native-user-original"))
        installed = comms.registry.declare(replace(thread, session_file=RegistrySessionLocation.from_path(source, workspace.comms.root)))
        assert installed.incarnation == thread.incarnation
        page = await view.transcript.get_transcript_page()
        assert page.after.session_file != old_page.after.session_file
        assert not old.accepts_commit(page.after)
        view.window.anchor()
        view.prompt.focus()
        view.transcript.dirty = view.transcript.commit_required = True
        publication = view.transcript.binding.capture(view.transcript, CommitPublication)
        assert publication.current() and publication.native_current()
        task = asyncio.create_task(publication.publish())
        try:
            await ui.until(task.done, seconds=8, why="the checkpoint published")
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await ui.step()
        (replacement,) = view.window.histories
        assert not old.is_attached and not live.is_attached
        assert not list(view.contents.query(AgentResponse)), "the covered live response is still mounted"
        await ui.until(lambda: ui.painted(view.window).count("FIRST_SAVED_NATIVE_RESPONSE") == 1,
                       why="the saved response drawn exactly once")
        assert replacement.page_source.through == page.after
        assert replacement.page_source.loader == view.transcript.get_transcript_page
        assert replacement.covers_incoming(notice.seq)
