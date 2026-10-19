"""Textual-facing: returning to a conversation paints its newest content in the first frame, and a reader who scrolled up stays where they were."""

import asyncio

from agent_comms.transcript_events import AssistantTranscript
from agent_comms.transcripts import NativeTranscriptCursor, TranscriptPage
from support.roots import FIXTURE_SNAPSHOT

from support.agents import detached
from support.stylesheets import INSTALLED
from toad.app import ToadApp
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.transcript_history import TranscriptHistory


class FrameApp(ToadApp):
    """Records the selected conversation's scroll and painted text for every frame drawn while `frames` is a list."""

    CSS_PATH = INSTALLED

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = None

    def _display(self, screen, renderable):
        if self.frames is not None and renderable is not None and not self._batch_count and screen is self.screen:
            session = self.selected_session
            conversation = session.query_one_optional(Conversation) if session is not None else None
            if conversation is not None:
                window = conversation.window
                region = window.content_region
                text = "\n".join(strip.text[region.x:region.right]
                                 for strip in screen._compositor.render_strips()[region.y:region.bottom])
                self.frames.append((self.selected_mode, window.scroll_y, window.max_scroll_y, text))
        return super()._display(screen, renderable)


async def long_history_then_other_tab(ui):
    conversation = ui.conversation
    response = await conversation.post(AgentResponse("\n\n".join(f"Old paragraph {i}" for i in range(40))))
    window = conversation.window
    window.anchor()
    await ui.step()
    other = await ui.new_session()
    return conversation, response, window, other


def at_bottom_showing(frames, mode, marker):
    chosen = [frame for frame in frames if frame[0] == mode]
    return bool(chosen) and all(y == maximum and marker in text for _, y, maximum, text in chosen), chosen


async def test_returning_to_a_following_conversation_paints_the_latest_activity_first(workspace):
    async with workspace.app(size=(100, 30), application=FrameApp) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        conversation, response, window, other = await long_history_then_other_tab(ui)
        await response.append_fragment("\n\n" + "\n\n".join(f"New paragraph {i}" for i in range(400)) + "\n\nLATEST-ACTIVITY")
        await ui.resize(75, 24)
        app.frames = []
        await ui.select_tab(owner)
        ok, frames = at_bottom_showing(app.frames, owner, "LATEST-ACTIVITY")
        assert ok, frames
        assert window.follows_tail


async def test_returning_to_a_conversation_the_reader_scrolled_up_keeps_the_position(workspace):
    async with workspace.app(size=(100, 30), application=FrameApp) as ui:
        owner = ui.selected_tab
        conversation, response, window, other = await long_history_then_other_tab(ui)
        await ui.select_tab(owner)
        window.scroll_relative(y=-8, animate=False, immediate=True)
        await ui.step()
        position = window.scroll_y
        assert not window.follows_tail
        await ui.select_tab(other)
        await response.append_fragment("\n\nLATEST-WHILE-READING")
        await ui.select_tab(owner)
        assert not window.follows_tail and window.scroll_y == position


async def test_returning_while_older_history_is_loading_paints_the_latest_page(workspace):
    async with workspace.app(size=(100, 30), application=FrameApp) as ui:
        app, _ = ui.textual
        owner = ui.selected_tab
        conversation, response, window, other = await long_history_then_other_tab(ui)
        await ui.select_tab(owner)
        await conversation.contents.remove_children()
        cursor = NativeTranscriptCursor("test", 100)
        page = TranscriptPage((AssistantTranscript("LATEST-PAGED-ACTIVITY"),), cursor, cursor, True, False, FIXTURE_SNAPSHOT)
        started, release = asyncio.Event(), asyncio.Event()

        async def load_page(**kwargs):
            started.set()
            await release.wait()
            return TranscriptPage(
                tuple(AssistantTranscript(f"Earlier activity {i}: " + "wrapped text " * 30) for i in range(100)),
                cursor, cursor, False, True, FIXTURE_SNAPSHOT)

        window.anchor()
        await conversation.contents.mount(TranscriptHistory(page, load_page))
        async with asyncio.timeout(5):
            await started.wait()
        await ui.select_tab(other)
        app.frames = []
        release.set()
        await ui.select_tab(owner)
        ok, frames = at_bottom_showing(app.frames, owner, "LATEST-PAGED-ACTIVITY")
        assert ok, frames


async def test_a_snapshot_published_into_a_conversation_paints_at_the_latest_activity(workspace):
    async with workspace.app(size=(100, 30), application=FrameApp) as ui:
        app, _ = ui.textual
        conversation = ui.conversation
        agent = detached(workspace.project, "snapshot-session")
        ui.attach_agent(agent)
        await conversation.contents.remove_children()
        cursor = NativeTranscriptCursor("test", 100)
        snapshot = TranscriptPage(
            tuple(AssistantTranscript(f"Snapshot paragraph {i}") for i in range(100))
            + (AssistantTranscript("LATEST-SNAPSHOT-ACTIVITY"),), cursor, cursor, True, False, FIXTURE_SNAPSHOT)
        app.frames = []
        await conversation.transcript.snapshot(snapshot)
        await ui.until(lambda: any("LATEST-SNAPSHOT-ACTIVITY" in frame[3] for frame in app.frames),
                       seconds=5, why="the snapshot's latest activity to be painted")
        await ui.step()
        painted = [frame for frame in app.frames
                   if "Snapshot paragraph" in frame[3] or "LATEST-SNAPSHOT-ACTIVITY" in frame[3]]
        assert painted and all(y == maximum and "LATEST-SNAPSHOT-ACTIVITY" in text
                               for _, y, maximum, text in painted), painted
