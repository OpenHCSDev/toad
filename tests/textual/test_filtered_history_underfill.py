"""Textual-facing: a filtered history fills an empty viewport by reading older pages into the window's scroll extent.

Not carried over from the old script: assertions on the count of mounted widgets (history is line-drawn now,
so there are no per-message widgets to count) and on per-message widgets being displayed (the fragments the
viewport shows are asked instead).
"""

from agent_comms.message_reference import MessageReference
from agent_comms.routing import MessageRoute, TurnRouting
from agent_comms.transcript_events import SentTranscript, ThinkingTranscript
from agent_comms.transcript_sources import TranscriptCursor, NativeCursor
from agent_comms.transcripts import TranscriptPage

from toad.widgets.message_filter import MessageCategory, RoutedMessage, all_categories
from toad.widgets.transcript_history import TranscriptHistory

FILE = "read-only-fixture"
ROUTED = frozenset(MessageCategory.members_with(RoutedMessage))
OLDER = SentTranscript("OLDER_ROUTED_MESSAGE", source=MessageReference(1, "underfill-outbound"),
                       routing=TurnRouting(reply=MessageRoute("owner", ("#team",))))


def hidden_tail(count: int, name: str = "HIDDEN_TAIL"):
    return TranscriptPage(tuple(ThinkingTranscript(f"{name}_{index}") for index in range(count)),
                          NativeCursor(FILE, 100), NativeCursor(FILE, 200), True, False)


def routed_shown(history) -> bool:
    overlay = history.filter.overlay
    return overlay is not None and overlay.is_mounted and any(fragment.events[0].text == OLDER.text
                                       for fragment in overlay.visible_fragments())


async def mount_then_filter(ui, page, loader):
    """Mount a history showing everything, then restrict the message categories as the user would."""
    history = TranscriptHistory(page, loader=loader)
    await ui.conversation.contents.mount(history)
    ui.conversation.window.anchor()
    ui.conversation.visible_categories = ROUTED
    return history


async def test_routed_filter_reads_an_older_page_to_fill_an_empty_viewport(workspace):
    async with workspace.app(size=(110, 44)) as ui:
        conversation = ui.conversation
        calls = []

        async def load_page(**kwargs):
            calls.append(kwargs)
            return TranscriptPage((OLDER,), NativeCursor(FILE, 0), NativeCursor(FILE, 100), False, True)

        tail = hidden_tail(90)
        history = await mount_then_filter(ui, tail, load_page)
        await ui.until(lambda: routed_shown(history), why="the older routed message in the filtered view")
        assert calls and len(calls) <= 3, "Underfill walked the same page indefinitely"
        assert conversation.visible_categories == ROUTED
        assert history.pages[-1].page.events == tail.events
        await ui.until_shows("OLDER_ROUTED_MESSAGE")


async def test_filter_over_more_hidden_records_than_the_budget_still_finds_the_routed_one(workspace):
    async with workspace.app(size=(110, 44)) as ui:
        conversation = ui.conversation
        calls = []

        async def load_page(**kwargs):
            calls.append(kwargs)
            return TranscriptPage((OLDER,), NativeCursor(FILE, 0), NativeCursor(FILE, 100), False, True)

        sparse = await mount_then_filter(ui, hidden_tail(340, "HIDDEN_OLDER"), load_page)
        await ui.until(lambda: routed_shown(sparse), why="the older routed message past 340 hidden records")
        assert len(calls) <= 3, "Sparse scan repeated a bounded page"
        assert sparse.filter.overlay is not None and sparse.filter.overlay.display
        await ui.until_shows("OLDER_ROUTED_MESSAGE")


async def test_clearing_the_filter_restores_the_transcript_and_setting_it_again_finds_the_routed_message(workspace):
    async with workspace.app(size=(110, 44)) as ui:
        conversation = ui.conversation

        async def load_page(**kwargs):
            return TranscriptPage((OLDER,), NativeCursor(FILE, 0), NativeCursor(FILE, 100), False, True)

        sparse = await mount_then_filter(ui, hidden_tail(340, "HIDDEN_OLDER"), load_page)
        await ui.until(lambda: routed_shown(sparse), why="the routed message under the filter")
        conversation.visible_categories = all_categories()
        await ui.until(lambda: sparse.filter.overlay is None or not sparse.filter.overlay.display,
                       why="the projection hidden once nothing is filtered")
        await ui.until(lambda: bool(sparse.visible_fragments()), why="the retained transcript shown again")
        conversation.visible_categories = ROUTED
        await ui.until(lambda: routed_shown(sparse), why="the routed message under the filter again")


async def test_history_with_no_routed_records_is_scanned_to_its_end_once(workspace):
    async with workspace.app(size=(110, 44)) as ui:
        reads = []

        async def only_hidden(**kwargs):
            reads.append(kwargs["before"].offset)
            offset = 50 if kwargs["before"].offset == 100 else 0
            return TranscriptPage((ThinkingTranscript("NO_ROUTE"),), NativeCursor(FILE, offset),
                                  NativeCursor(FILE, kwargs["before"].offset), bool(offset), True)

        empty = await mount_then_filter(ui, hidden_tail(90), only_hidden)
        await ui.until(lambda: empty.filter.before is not None and not empty.filter.has_older,
                       why="the scan to reach the oldest record")
        assert reads == [100, 50], reads
        await ui.step(0.2)
        assert reads == [100, 50], "No-route history was scanned again"
