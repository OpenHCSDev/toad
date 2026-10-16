"""Textual-facing: the history window's scroll position decides when an older page is read.

Not carried over from the old script: the count of mounted widgets in the failure message (history is
line-drawn; there are no per-message widgets).
"""

from agent_comms.message_reference import MessageReference
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcript_events import AssistantTranscript, SentTranscript, ThinkingTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage

from toad.widgets.message_filter import MessageCategory, RoutedMessage
from toad.widgets.transcript_history import TranscriptHistory

FILE = "prefetch-fixture"


async def test_older_page_is_read_before_the_viewport_reaches_the_top(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        window = ui.conversation.window
        calls = []

        async def loader(**kwargs):
            calls.append((window.scroll_y, kwargs))
            return TranscriptPage((AssistantTranscript("OLDER_PREFETCHED_RECORD"),),
                                  NativeCursor(FILE, 0), NativeCursor(FILE, 100), False, True)

        tail = tuple(AssistantTranscript(f"Record {i}\n\n" + "Long line\n" * 5) for i in range(64))
        history = TranscriptHistory(TranscriptPage(
            tail, NativeCursor(FILE, 100), NativeCursor(FILE, 200), True, False), loader=loader)
        await ui.conversation.contents.mount(history)
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > history.prefetch_distance, why="a scrollable history")
        assert history.pages[0].page.before.offset == 100, "Lookahead mounted old content at the tail"
        window.release_anchor()

        def scrolled_toward_the_top():
            window.scroll_to(y=history.prefetch_distance - 1, animate=False, immediate=True)
            return history.pages[0].page.before.offset == 0

        await ui.until(scrolled_toward_the_top, seconds=8, why="the older page prepended")
        assert window.scroll_y > 2, "Older history was only read at the top"
        assert calls[0][1]["before"].offset == 100
        assert len(calls) == 1, "Foreground paging repeated the prepared page read"


async def test_filtered_older_page_is_read_before_the_viewport_reaches_the_top(workspace):
    async with workspace.app(size=(110, 38)) as ui:
        window = ui.conversation.window
        calls = []
        route = TurnRouting(reply=MessageRoute("owner", ("#team",)))

        async def loader(**kwargs):
            calls.append(window.scroll_y)
            return TranscriptPage((SentTranscript("FILTERED_PREFETCH", routing=route,
                                                  source=MessageReference(2, "prefetch-filtered")),),
                                  NativeCursor(FILE, 0), NativeCursor(FILE, 100), False, True)

        tail = (*(ThinkingTranscript(f"HIDDEN_{index}") for index in range(90)),
                SentTranscript("VISIBLE_ROUTE\n\n" + "Long routed line\n\n" * 150, routing=route,
                               source=MessageReference(1, "prefetch-visible")))
        history = TranscriptHistory(TranscriptPage(
            tail, NativeCursor(FILE, 100), NativeCursor(FILE, 200), True, False), loader=loader)
        await ui.conversation.contents.mount(history)
        window.anchor()
        await ui.until(lambda: window.max_scroll_y > history.prefetch_distance, why="a scrollable history")
        ui.conversation.visible_categories = frozenset(MessageCategory.members_with(RoutedMessage))
        await ui.step()
        assert window.max_scroll_y > history.prefetch_distance, "the routed message alone must still be scrollable"
        assert history.filter.overlay is None, "Lookahead published filtered rows at the tail"
        window.release_anchor()

        def scrolled_toward_the_top():
            window.scroll_to(y=history.prefetch_distance - 1, animate=False, immediate=True)
            return history.filter.overlay is not None

        await ui.until(scrolled_toward_the_top, seconds=8, why="the filtered older page requested")
        assert window.scroll_y > 2, "Filtered result was only read at the top"
        assert len(calls) == 1
