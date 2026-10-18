"""A channel or direct conversation drawn by the line history, with its read marks."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from agent_comms.messages import Message

from toad.screens.session_view import SessionView
from toad.transcript_preparation import PreparedTranscriptPage, PreparedPageSource, SavedHistory, NoMoreHistory
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.transcript_state import LatestViewportRequest
from toad.widgets.history_anchor import LatestPosition
from toad.widgets.message_filter import OtherCategory, all_categories
from toad.widgets.message_notifications import VisibleReadMarking
from toad.widgets.transcript_history import LineHistory
from toad.message_rows import IrcMessageStyle, WireMessageStyle
from toad.wire_history import PreparedWirePage, WirePage, WireSource

if TYPE_CHECKING:
    from agent_comms.historical_views import ConversationRevision

class WireHistory(VisibleReadMarking, LineHistory):
    """The line history of a channel or direct conversation.

    Paging, preparation, trimming and the reader's position are the line
    history's. This adds what a wire conversation has: a source that grows
    under one viewer's reading of it, messages marked read when their text is
    seen, notification states and two styles.
    """

    def __init__(self, prepared: PreparedTranscriptPage,
                 history: PreparedPageSource, *, view) -> None:
        self.view = view
        super().__init__(prepared, history)
        # Core's source observation is independent of paint readiness.
        self.revision: ConversationRevision | None = None

    # The source

    def open(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self._history.close()
        self._history = SavedHistory(source, self.through, self.app.preparation)

    @property
    def source(self) -> WireSource | NoMoreHistory:
        return self._history.source

    @property
    def style(self) -> WireMessageStyle:
        return self.source.style

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return all(view.page.undrawn for view in self.pages)

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.source, self.selected_categories

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionView).is_current)

    async def bus_is_current(self, comms) -> bool:
        """Whether the route still selects this bus and this history still reads it."""
        from agent_comms.route_selection import root_is_current

        current = await self.app.preparation.run_thread(root_is_current, comms.root)
        return current and self.source.is_current(comms)

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        return await self.source.current_in(self, snapshot)

    @property
    def selected_categories(self):
        # Every wire message is in one category: a filter shows all or none.
        return (all_categories() if OtherCategory in self.view.visible_categories
                else frozenset())

    # Reading the source

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.source
        observed = await self.app.preparation.run_thread(
            source.observe, self.revision)
        if source is not self.source:
            return False
        if observed is not None:
            # Record Core's observation before asynchronous drawing. A pending
            # viewport must not turn the same scope into another replacement.
            self.revision = observed.revision
            if observed.replaced:
                await self.show_newest(observed.through, PreparedWirePage.empty(WirePage.unread()))
                return not self.undrawn
            if not self.undrawn:
                return await self.extend(observed.through)
            self.extend_source(observed.through)
        elif not self.undrawn:
            # A recorded observation may still have an unfinished page read.
            return (self.pages[-1].page.after != self.through
                    and await self.extend(self.through))
        # The existing prepared reader owns this pending page. Retry drawing it,
        # not clearing its source and starting the same read again.
        await self._jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)))
        return not self.undrawn

    # What is drawn

    async def accept_extension(self, edge, prepared) -> bool:
        if edge.page.accepts(prepared.page.source, self.source.kind.history_view):
            return True
        await self.show_newest(self.through, PreparedWirePage.empty(WirePage.unread()))
        return False

    @property
    def messages(self) -> tuple[Message, ...]:
        """The messages the drawn rows show, oldest first."""
        return tuple(fragment.message for fragment in self.fragments_in_range)

    def draws(self, message: Message) -> bool:
        """Whether the drawn rows include this message."""
        return any(drawn.view_key == message.view_key for drawn in self.messages)

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        if not self.can_draw_on_screen:
            return
        style = self.style.next()
        self.open(self.source.restyled(style))
        await self._show([(fragment, replace(fragment.shown, style=style))
                          for fragment in self.fragments])
        self.window.scroll_end(animate=False)

    def notification_read(self, references):
        from agent_comms.ui_model.observation import ReadNotifications

        return ReadNotifications(str(self.source.comms.root), references)

    # Read marks

    def read_visible(self):
        if not self.is_attached:
            return None
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return None
        return self._mark_read(self.source_snapshot())

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        if not await self.source_is_current(snapshot):
            if snapshot.current(self):
                self.view.display = False
            elif self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
            return
        seen = tuple(fragment for fragment in self.read_fragments() if fragment.evidence is not None)
        historical = next((fragment.evidence for fragment in seen
                           if fragment.evidence.historical_display is not None), None)
        if historical is not None:
            await self._mark_historical(
                historical, tuple(fragment for fragment in seen if fragment.evidence is historical),
                snapshot)
        elif (selected := self.source.kind.seen_page(self, seen)) is not None:
            await self._mark_page(*selected, snapshot)

    async def _mark_historical(self, page, marked, snapshot: HistorySourceSnapshot) -> None:
        from agent_comms.route_selection import implicit_root, run_selected_write

        comms = self.source.comms
        displayed = page.historical_display.select({fragment.message.seq for fragment in marked})
        try:
            await asyncio.to_thread(run_selected_write, comms.root,
                                    comms.views.mark_historical_view_read, displayed,
                                    implicit=implicit_root())
        except ValueError:
            # The attached history changed; this page's evidence marks nothing any more.
            marked = tuple(fragment for fragment in self.fragments if fragment.evidence is page)
        if snapshot.current(self):
            for fragment in marked:
                fragment.evidence = None

    async def _mark_page(self, page, marked, snapshot: HistorySourceSnapshot) -> None:
        source = self.source
        try:
            await source.kind.mark_read(source.comms, source.target, str(source.project), page)
            if snapshot.current(self):
                for fragment in marked:
                    fragment.evidence = None
        except ValueError:
            # The viewer, peer, channel scope or bus changed after the page
            # was read: draw the conversation as it is read now.
            if snapshot.current(self):
                await self._clear(PreparedWirePage.empty(WirePage.unread()))
                await self.view._refresh()
        finally:
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
