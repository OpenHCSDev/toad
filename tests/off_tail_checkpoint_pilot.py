"""Committed arrivals retire without moving or acknowledging the reader's viewport."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.transcripts import TranscriptCursor, TranscriptPage
from agent_comms.transcript_events import AssistantTranscript
from textual.screen import Screen
from textual.selection import SELECT_ALL
from textual.widgets import Static

from committed_history_pilot import SnapshotAgent
from history_scroll_frames_pilot import ScrollFrameApp
from agent_comms.messages import Message, MessageType
from agent_comms.routing import TurnRouting
from agent_comms.transcript_events import UserTranscript
from toad.widgets.agent_response import AgentResponse
from toad.widgets.committed_presentation import CheckpointBarrier
from toad.widgets.incoming_message import IncomingMessage
from toad.widgets.transcript_history import TranscriptHistory


def routed(sequence, text):
    message = Message("peer", "owner", text, MessageType.INFO, seq=sequence)
    return UserTranscript(text, routing=TurnRouting((message,), None))


class PagedAgent(SnapshotAgent):
    """Append-only source with exact cursors, bounded pages and a controllable read."""

    def __init__(self):
        super().__init__(None)
        self.ready = True
        self.identity = "off-tail-fixture"
        self.events = [AssistantTranscript(f'Saved {index}\n\n' + '\n'.join((f'- line {line}' for line in range(16)))) for index in range(60)]
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    @property
    def cursor(self):
        return TranscriptCursor(self.identity, len(self.events))

    async def get_transcript_page(self, *, before=None, after=None, through=None):
        self.requests.append((before, after, through))
        limit = len(self.events) if through is None else through.offset
        if after is None:
            stop = min(limit, before.offset if before is not None else limit)
            start = max(0, stop - 8)
        else:
            start, stop = after.offset, min(limit, after.offset + 8)
        page = TranscriptPage(tuple(self.events[start:stop]), TranscriptCursor(self.identity, start),
                              TranscriptCursor(self.identity, stop), start > 0, stop < limit)
        self.entered.set()
        await self.release.wait()
        return page


class LocalBarrier(CheckpointBarrier, Static):
    pass


async def checkpoint(view):
    view.transcript.dirty = view.transcript.checkpoint_required = True
    await view.transcript.request().wait()


async def exercise(app, pilot):
    view = app.selected_session.conversation
    agent = PagedAgent()
    view.set_reactive(type(view).agent, agent)
    view.agent_ready = True
    history = TranscriptHistory(await agent.get_transcript_page(), agent.get_transcript_page)
    # Drive paging explicitly: this isolates commit retirement from prefetch
    # and lets the assertions distinguish source evidence from widget admission.
    with (patch.object(TranscriptHistory, "_check_edges"),
          patch.object(TranscriptHistory, "_warm_pages")):
        await view.contents.mount(history)
        await pilot.pause()
        window = view.window
        window.release_anchor()
        window.scroll_to(y=5, animate=False, immediate=True)
        await pilot.pause()
        assert window.max_scroll_y > 20 and not window.follows_tail
        pages, fragments = tuple(history.pages), history.fragment_views
        marker = fragments[0]
        expected_y = marker.region.y - window.content_region.y
        position, revision = window.scroll_y, window.scroll_revision
        frames = []
        app.observed = marker, window, frames
        view.transcript.displayed_cursor = displayed = agent.cursor
        view.prompt.text = "Unsent checkpoint draft"
        local = Static("Local-only note")
        await view.contents.mount(local)
        peak = 0
        for cycle in range(12):
            texts = [f"Committed cycle {cycle} row {index}" for index in range(36)]
            agent.events.extend(AssistantTranscript(text) for text in texts)
            blocks = [AgentResponse(text) for text in texts]
            await view.contents.mount(*blocks)
            await checkpoint(view)
            await pilot.pause(0)
            peak = max(peak, len(view.contents.children))
            assert all(not block.is_attached for block in blocks)
            assert history.through == agent.cursor and history.has_newer
            assert tuple(history.pages) == pages and history.fragment_views == fragments
            assert window.scroll_y == position and window.scroll_revision == revision
            assert not window.follows_tail and view.transcript.displayed_cursor == displayed
            assert local.is_attached and view.prompt.text == "Unsent checkpoint draft"
        assert frames and set(frames) == {expected_y}, (expected_y, frames)
        app.observed = None
        assert peak <= 3, peak
        with patch.object(app.coordination_access.service.views, 'mark_thread_view_read') as acknowledge:
            await app.mark_visible_thread_read()
            acknowledge.assert_not_called()

        # Exact routed identities may be outside the newest native page. Read
        # their committed interval, without mounting any of its unread bodies.
        saved = IncomingMessage("peer", "saved identity", "owner", sequence=41)
        missing = IncomingMessage("peer", "not persisted", "owner", sequence=42)
        await view.contents.mount(saved, missing)
        start = history.through
        agent.events.append(routed(41, "saved identity"))
        agent.events.extend(AssistantTranscript(f'Evidence gap {i}') for i in range(24))
        agent.requests.clear()
        await checkpoint(view)
        assert not saved.is_attached and missing.is_attached
        assert any(after == start for _, after, _ in agent.requests)
        assert history.fragment_views == fragments

        # Native selection and a local interactive barrier protect live content.
        protected = Static("Protected source block")
        block = AgentResponse("Selected committed block")
        agent.events.append(AssistantTranscript('Selected committed block'))
        await view.contents.mount(block)
        await block.mount(protected)
        app.screen.selections = {protected: SELECT_ALL}
        through = history.through
        await checkpoint(view)
        assert block.is_attached and history.through == through
        app.screen.clear_selection()
        protected.can_focus = True
        protected.focus(scroll_visible=False)
        await pilot.pause()
        await checkpoint(view)
        assert block.is_attached and history.through == through
        view.prompt.focus()
        barrier = LocalBarrier("Interactive local session")
        await view.contents.mount(barrier)
        await checkpoint(view)
        assert block.is_attached and history.through == through
        await barrier.remove()
        await checkpoint(view)
        assert not block.is_attached

        # Reader input during source I/O supersedes the retirement transaction.
        late = AgentResponse("Commit whose reader moves")
        agent.events.append(AssistantTranscript('Commit whose reader moves'))
        await view.contents.mount(late)
        agent.entered.clear()
        agent.release.clear()
        task = asyncio.create_task(checkpoint(view))
        await asyncio.wait_for(agent.entered.wait(), 5)
        # Suppress the scroll watcher's automatic retry while inspecting the
        # superseded transaction; retry explicitly after its assertions.
        view.transcript.dirty = False
        window.scroll_relative(y=1, animate=False, immediate=True)
        await pilot.pause(0)
        agent.release.set()
        await task
        assert late.is_attached
        await checkpoint(view)
        assert not late.is_attached

        # An ordinary arrival after the source capture has no coverage claim.
        old = AgentResponse("Committed before delayed read")
        agent.events.append(AssistantTranscript('Committed before delayed read'))
        await view.contents.mount(old)
        agent.entered.clear()
        agent.release.clear()
        task = asyncio.create_task(checkpoint(view))
        await asyncio.wait_for(agent.entered.wait(), 5)
        arrival = AgentResponse("Uncommitted concurrent arrival")
        await view.contents.mount(arrival)
        agent.release.set()
        await task
        assert not old.is_attached and arrival.is_attached
        await arrival.remove()

        # A saved block currently being read must remain visible in place.
        text = "Visible committed block\n\n" + "\n".join(f"- reading {i}" for i in range(24))
        visible = AgentResponse(text)
        agent.events.append(AssistantTranscript(text))
        await view.contents.mount(visible)
        await pilot.pause()
        window.scroll_to(y=window.max_scroll_y - 5, animate=False, immediate=True)
        window.release_anchor()
        await pilot.pause()
        through = history.through
        await checkpoint(view)
        assert visible.is_attached and history.through == through
        view.transcript.dirty = False
        window.scroll_to(y=position, animate=False, immediate=True)
        await pilot.pause()
        await checkpoint(view)
        assert not visible.is_attached

        # Invalid coverage progress is rejected without losing the live cohort
        # or turning a source replacement race into a fatal worker exception.
        invalid = AgentResponse("Pending during invalid coverage")
        agent.events.append(AssistantTranscript('Pending during invalid coverage'))
        agent.events.extend(AssistantTranscript(f'Invalid scan {i}') for i in range(12))
        await view.contents.mount(invalid)
        through = history.through
        load = agent.get_transcript_page

        async def invalid_progress(**kwargs):
            after = kwargs.get("after")
            if after is not None:
                return TranscriptPage((), after, after, True, True)
            return await load(**kwargs)

        with patch.object(agent, "get_transcript_page", invalid_progress):
            await checkpoint(view)
        assert invalid.is_attached and history.through == through
        await checkpoint(view)
        assert not invalid.is_attached

        # Incompatible source identities cannot retire the current live cohort.
        old = AgentResponse("Original source block")
        await view.contents.mount(old)
        through = history.through
        agent.identity = "replacement-source"
        await checkpoint(view)
        assert old.is_attached and history.through == through
        agent.identity = through.session_file
        saved_events = agent.events
        agent.events = agent.events[:30]
        await checkpoint(view)
        assert old.is_attached and history.through == through
        agent.events = saved_events
        await old.remove()

        # A parked tab has no viewport to repaint and must not wait for a frame
        # which its inactive screen cannot deliver.
        original_mode = app.selected_mode
        app.add_mode("checkpoint-parked", Screen)
        view.transcript.dirty = False
        await app.switch_mode("checkpoint-parked")
        hidden = AgentResponse("Committed while inactive")
        agent.events.append(AssistantTranscript('Committed while inactive'))
        await view.contents.mount(hidden)
        await checkpoint(view)
        assert not hidden.is_attached and history.through == agent.cursor
        assert history.fragment_views == fragments
        assert view.transcript.displayed_cursor == displayed and not window.follows_tail
        await app.switch_mode(original_mode)
        await pilot.pause()

        # All retired source content remains navigable from the same pager.
        await missing.remove()
        await local.remove()
        view.transcript.dirty = False
        assert history.through == agent.cursor, (history.through, agent.cursor)
        window.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        history._loading = True
        await history._jump_latest(window.scroll_revision)
        await pilot.pause()
        assert history.pages[-1].page.after == agent.cursor, (history.pages[-1].page.after, agent.cursor)
        assert any("Committed while inactive" in event.text
                   for fragment in history.fragment_views for event in fragment.fragment.events), (
                       [(page.start, page.stop, page.page.events) for page in history.pages],
                       history.fragment_views,
                   )
        assert window.follows_tail and view.prompt.text == "Unsent checkpoint draft"
    print(f"off-tail checkpoint: 432 committed live blocks retired; peak {peak} outer widgets; "
          "stable painted viewport, selection, identities, supersession and source access")


async def main():
    with TemporaryDirectory(prefix="toad-off-tail-checkpoint-") as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / "wire"), XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"), XDG_DATA_HOME=str(root / "data"))
        app = ScrollFrameApp(project_dir=str(root))
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            async with asyncio.timeout(60):
                await exercise(app, pilot)
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()


if __name__ == "__main__":
    asyncio.run(main())
