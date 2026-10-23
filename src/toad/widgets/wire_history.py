"""A channel or direct conversation drawn by the line history, with its read marks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.coordination_errors import StaleRevision
from agent_comms.historical_views import ConversationObservation
from agent_comms.messages import Message

from toad.screens.session_view import SessionView
from toad.transcript_preparation import ClosedHistory, PreparedTranscriptPage
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.widgets.message_notifications import (
    NothingToRead,
    PaintedRead,
    VisibleReadMarking,
)
from toad.widgets.transcript_history import ConversationHistory
from toad.wire_history import PreparedWirePage, WirePage, WirePageBuffer, WireSource

if TYPE_CHECKING:
    from toad.widgets.comms_chat import CommsChatView


class WireHistory[ViewT: CommsChatView](VisibleReadMarking, ConversationHistory[ViewT]):
    """The line history of a channel or direct conversation.

    Paging, preparation, trimming and the reader's position are the line
    history's. This adds what a wire conversation has: a source that grows
    under one viewer's reading of it, messages marked read when their text is
    seen, notification states and two styles.
    """

    page_source: WirePageBuffer | ClosedHistory

    def __init__(self, prepared: PreparedTranscriptPage, page_source: WirePageBuffer | ClosedHistory,
                 *, view: ViewT, notification_view, **kwargs) -> None:
        super().__init__(prepared, page_source, view=view,
                         notification_view=notification_view, **kwargs)

    @classmethod
    def empty_page(cls):
        return PreparedWirePage.empty(WirePage.unread())

    # The source

    def initialize_source(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self.page_source.close()
        self.page_source = WirePageBuffer(source, self.page_source.through, self.app.preparation,
                                          revision=ConversationObservation())

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return all(view.prepared.page.undrawn for view in self.pages)

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.page_source.reload_key(), self.selected_categories

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionView).is_current)

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        source = self.page_source
        if not snapshot.current(self):
            return False
        return (await source.route_is_current()
                and source is self.page_source and snapshot.current(self))

    @property
    def selected_categories(self):
        return self.view.visible_categories

    # Reading the source

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.page_source
        observed = await source.observe_changes(source.revision)
        if source is not self.page_source:
            return False
        return await observed.apply(self, source)

    # What is drawn

    def rows_published(self) -> None:
        super().rows_published()
        if not self.undrawn and (placeholder := self.view.query_one_optional("#history-loading")):
            placeholder.remove()

    def draws(self, message: Message) -> bool:
        """Whether the drawn rows include this message, checking the newest first."""
        return any(fragment.message.view_key == message.view_key
                   for fragment in reversed(self.fragments_in_range))

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        await self.page_source.change_style(self)

    # Read marks

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        if self.can_draw_on_screen:
            self.mark_visible()

    def source_resumed(self) -> None:
        self.mark_visible()

    def read_visible(self) -> PaintedRead:
        if not self.is_attached:
            return NothingToRead()
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return NothingToRead()
        return self.page_source.painted_read(self)

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.view.display = False
            elif self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        if (selected := self.page_source.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_page(self, page, marked, snapshot: HistorySourceSnapshot) -> None:
        source = self.page_source
        try:
            await source.mark_page(page)
            if snapshot.current(self):
                for fragment in marked:
                    fragment.evidence = None
        except StaleRevision:
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                source.revision = ConversationObservation()
                await self.view._refresh()
        finally:
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
