"""A channel or direct conversation drawn by the line history, with its read marks."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from typing import TYPE_CHECKING

from agent_comms.messages import Message

from toad.screens.session_view import SessionView
from toad.transcript_preparation import PageRequest, PreparedPageSource
from toad.transcript_source_preparation import HistorySourceSnapshot
from toad.transcript_state import LatestViewportRequest
from toad.widgets.history_anchor import HeldReaderDestination, LatestPosition
from toad.widgets.message_filter import OtherCategory, all_categories
from toad.widgets.transcript_history import LineHistory, TranscriptPageView
from toad.message_rows import IrcMessageStyle, WireMessageStyle
from toad.wire_history import AfterSequence, WireFragment, WirePage, WirePageBuffer, WireSource

if TYPE_CHECKING:
    from agent_comms.presentation import WireRevision


class WireHistory(LineHistory):
    """The line history of a channel or direct conversation.

    Paging, preparation, trimming and the reader's position are the line
    history's. This adds what a wire conversation has: a source that grows
    under one viewer's reading of it, messages marked read when their text is
    seen, notification states and two styles.
    """


    def __init__(self, view) -> None:
        # The view's message filter is read while the line history is built.
        self.view = view
        super().__init__(WirePage.unread(), None, fragments=())
        # The store revision and the viewer's reading the drawn pages belong to.
        self.revision: WireRevision | None = None
        self.identity: tuple | None = None
        # A read mark is being written; the next one waits for it.
        self.marking = False

    # The source

    def open(self, source: WireSource) -> None:
        """Bind the conversation to read; the first refresh draws its newest page."""
        self.loader = source

    @property
    def source(self) -> WireSource | None:
        return self.loader

    @property
    def style(self) -> WireMessageStyle:
        return self.source.style if self.source is not None else IrcMessageStyle()

    @property
    def undrawn(self) -> bool:
        """Nothing of the bound source has been drawn yet."""
        return self.revision is None

    @property
    def source_identity(self):
        # Growth of the bus is not another source: reads ahead stay valid.
        return self.loader, self.selected_categories

    @property
    def can_draw_on_screen(self) -> bool:
        return (super().can_draw_on_screen
                and self.view.query_ancestor(SessionView).is_current)

    async def bus_is_current(self, comms) -> bool:
        """Whether the route still selects this bus and this history still reads it."""
        from agent_comms.route_selection import root_is_current

        current = await self.app.preparation.run_thread(root_is_current, comms.root)
        return current and self.source is not None and self.source.comms is comms

    async def source_is_current(self, snapshot: HistorySourceSnapshot) -> bool:
        """Whether the route still selects this source's bus and nothing replaced the history."""
        source = self.source
        if source is None or not snapshot.current(self):
            return False
        return (await self.bus_is_current(source.comms)
                and source is self.source and snapshot.current(self))

    def source_failed(self, error) -> None:
        self.view.status = f"Wire error: {error}"

    def _reader(self) -> PreparedPageSource:
        reader = self._page_buffer
        if reader is None or reader.loader is not self.loader:
            if reader is not None:
                reader.close()
            self._page_buffer = reader = WirePageBuffer(self.loader, self.through, self.app.preparation)
        # Pages of earlier messages stay prepared while the bound moves.
        reader.through = self.through
        return reader

    @property
    def selected_categories(self):
        # Every wire message is in one category: a filter shows all or none.
        return (all_categories() if OtherCategory in self.view.visible_categories
                else frozenset())

    def source_resumed(self) -> None:
        # Returning to the tab shows its messages again: what is on screen is read.
        self.mark_visible()

    # Reading the source

    async def read_changes(self) -> bool:
        """Draw what changed in the source; False when the stores are as last drawn."""
        source = self.source
        observed = await self.app.preparation.run_thread(
            source.observe, self.revision, self.through, self.identity)
        if observed is None or source is not self.source:
            return False
        if observed.replaced:
            await self.show_newest(observed.through)
            if self.has_newer and self.pages[-1].page.source is None:
                # The newest page was not drawn (the reader moved, or the view
                # was left): the same stores must be read again.
                return False
        elif not await self.extend(observed.through):
            return False
        self.revision = observed.revision
        return True

    async def show_newest(self, through: AfterSequence) -> None:
        """Replace what is drawn with the newest page of the source as read now."""
        await self._clear()
        self.extend_source(through)
        await self._jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)))
        source = self.pages[-1].page.source
        if source is not None:
            self.identity = self.source.kind.display_identity(source)

    async def _clear(self) -> None:
        """Forget every drawn page and everything prepared: they belong to another reading."""
        async with self.window.history_lock:
            async with self.window.preserve_history(root=self):
                self._generation += 1
                if self._page_buffer is not None:
                    self._page_buffer.close()
                    self._page_buffer = None
                self.revision = self.identity = None
                if len(self.pages) == 1 and self.pages[0].page.source is None:
                    return
                retired = tuple(self.pages)
                view = TranscriptPageView(WirePage.unread(), fragments=(),
                                      batch_size=self.budget.batch_items)
                view.visible_categories = self.selected_categories
                await self.mount(view, before=self.newer)
                self.pages = deque([view])
                self.through = view.page.after
                self.remove_children(retired)
                self._update_edges()

    async def extend(self, through: AfterSequence) -> bool:
        """The bus grew to `through`: draw this conversation's new messages for a tail reader.

        A reader elsewhere keeps their place and is offered the jump to them.
        False when the drawn pages changed during the read; the next refresh
        reads again.
        """
        if through.cursor > self.through.cursor:
            self.through = through
        edge = self.pages[-1]
        if (edge.page.after != self.through
                and (destination := HeldReaderDestination.held(self.window)) is not None
                and await destination.source_arrived(self)):
            return True
        if edge.page.after == self.through:
            return True
        if self.has_newer:
            # The drawn pages stop short of the end: paging from their edge
            # reaches the new messages.
            if not edge.page.has_newer:
                edge.page = replace(edge.page, has_newer=True)
            return True
        snapshot = self.source_snapshot()
        prepared = await self._reader().get(PageRequest(after=edge.page.after))
        # A page read from a bus the route no longer selects is never drawn.
        if (not await self.source_is_current(snapshot)
                or self.pages[-1] is not edge or self.has_newer):
            return False
        if (self.identity is not None
                and self.source.kind.display_identity(prepared.page.source) != self.identity):
            await self.show_newest(self.through)
        elif not prepared.fragments:
            edge.page = replace(edge.page, after=prepared.page.after)
        elif not self.window.follows_tail:
            edge.page = replace(edge.page, has_newer=True)
            self._update_edges()
        else:
            await self._load_page(False, prepared, fresh=True)
            if self.pages[-1].page.has_newer and self.window.follows_tail:
                # More arrived than one page holds: go to the newest instead
                # of drawing every page between.
                await self._jump_latest(LatestViewportRequest(LatestPosition.hold(self.window)))
        return True

    async def _extend_and_trim(self, edge, older, local, page, protected, fragments, prepared=None,
                               *, fresh=False):
        if page is not None and not fragments:
            # Nothing of this conversation lies in that range: the edge page covers it.
            edge.page = (replace(edge.page, before=page.before, has_older=page.has_older) if older
                         else replace(edge.page, after=page.after, has_newer=page.has_newer))
            self._update_edges()
            return
        await super()._extend_and_trim(edge, older, local, page, protected, fragments, prepared,
                                       fresh=fresh)

    def prepare_viewport(self) -> None:
        super().prepare_viewport()
        if self.can_draw_on_screen:
            # The shared pager already checked feedback; wire pages also mark paint.
            self.mark_visible()

    # What is drawn

    @property
    def wire_fragments(self) -> tuple[WireFragment, ...]:
        return tuple(fragment for page in self.pages for fragment in page.fragments)

    @property
    def messages(self) -> tuple[Message, ...]:
        """The messages the drawn rows show, oldest first."""
        return tuple(fragment.message for fragment in self.fragments_in_range)

    def draws(self, message: Message) -> bool:
        """Whether the drawn rows include this message."""
        return any(drawn.view_key == message.view_key for drawn in self.messages)

    def read_fragments(self) -> tuple[WireFragment, ...]:
        """Fragments whose own text has a row in the viewport."""
        if not self.is_attached or not self.can_draw_on_screen:
            return ()
        return tuple(
            fragment for page in self.pages for fragment, rows, lines in page.visible_rows(self.window)
            if (text := fragment.text_rows(lines)) and rows.start < text.stop and text.start < rows.stop)

    async def toggle_style(self) -> None:
        """Draw every message in the other style, here and in pages read from now on."""
        if self.source is None or not self.can_draw_on_screen:
            return
        style = self.style.next()
        self.open(self.source.restyled(style))
        await self._show([(fragment, replace(fragment.shown, style=style))
                          for fragment in self.wire_fragments])
        self.window.scroll_end(animate=False)

    def notification_read(self, references):
        from agent_comms.ui_model.observation import ReadNotifications

        return ReadNotifications(str(self.source.comms.root), references)

    # Read marks

    def mark_visible(self) -> None:
        """Mark read the messages whose text is on screen, when Core's page evidence allows."""
        if self.marking or not self.is_attached or self.source is None:
            return
        if not any(fragment.evidence is not None for fragment in self.read_fragments()):
            return
        self.marking = True
        self.view.run_worker(self._mark_read(self.source_snapshot()), group="comms-painted-read")

    async def _mark_read(self, snapshot: HistorySourceSnapshot) -> None:
        try:
            if not await self.source_is_current(snapshot):
                if snapshot.current(self):
                    self.view.display = False
                elif self.is_attached:
                    # The history was restyled or redrawn while this waited:
                    # what is on screen now is marked from its own snapshot.
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
        finally:
            self.marking = False

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
            marked = tuple(fragment for fragment in self.wire_fragments if fragment.evidence is page)
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
                await self._clear()
                await self.view._refresh()
        finally:
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
