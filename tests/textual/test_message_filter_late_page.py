"""Textual-facing: a conversation's history widget drops an older page that arrives after the category filter changed."""

import asyncio

from agent_comms.messages import Message, MessageType
from agent_comms.routing import MessageRoute
from agent_comms.transcript_events import AssistantTranscript, IncomingTranscript, ThinkingTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage
from toad.widgets.message_filter import InboundCategory, ThinkingCategory
from toad.widgets.transcript_history import TranscriptHistory


async def test_late_older_page_from_a_previous_filter_is_not_shown(workspace):
    async with workspace.app(size=(110, 37)) as ui:
        app, _ = ui.textual
        view = ui.conversation
        file = "fixture"
        cursor = NativeCursor(file, 100)
        entered, release = asyncio.Event(), asyncio.Event()
        message = Message("peer", "owner", "OLD_INBOUND", MessageType.INFO)
        incoming = IncomingTranscript(message.body, route=MessageRoute(message.sender, (message.target,)),
                                      source=message.reference)
        thinking = ThinkingTranscript("OLDER_THINKING")
        calls = []

        async def older(**kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            return TranscriptPage((incoming, thinking), NativeCursor(file, 0), cursor, False, True)

        tail = tuple(AssistantTranscript(f"unselected {i}\n" + "long text " * 20) for i in range(24))
        pager = TranscriptHistory(TranscriptPage(tail, cursor, NativeCursor(file, 200), True, False),
                                  loader=older)
        try:
            await view.contents.mount(pager)
            view.visible_categories = frozenset((InboundCategory,))
            view.window.release_anchor()
            view.window.scroll_to(y=0, animate=False, immediate=True)
            await asyncio.wait_for(entered.wait(), 5)
            view.visible_categories = frozenset((ThinkingCategory,))
            release.set()

            def thinking_shown():
                return pager.filter.overlay is not None and any(
                    fragment.events[0].text == "OLDER_THINKING" for fragment in pager.filter.overlay.fragments_in_range)

            await ui.until(thinking_shown, seconds=8, why="the selected thinking page in older history")
            assert all(fragment.events[0].text != "OLD_INBOUND" for fragment in pager.filter.overlay.fragments_in_range)
            assert len(calls) <= 2 and view.window.follows_tail is False
        finally:
            release.set()
