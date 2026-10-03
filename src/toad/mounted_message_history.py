"""Bounded mounted wire-message publication and displayed-only read receipts."""
from __future__ import annotations
import asyncio
from abc import abstractmethod
from functools import cached_property
from agent_comms.declared_family import DeclaredFamily
from agent_comms.message_page import MessagePage
from agent_comms.messages import Message as WireMessage
from textual import containers
from textual.widget import Widget
from toad.block_navigation import ConversationBlock, ChildBlockCursor
from toad.widgets.conversation import CategorizedMount
from toad.widgets.message_filter import CategorizedBlock, apply_block_filter
from toad.message_viewport import AcknowledgementViewport
from toad.channel_preparation import ChannelHistoryReader, HistoryReadResult
from toad.screens.session_view import SessionView
from toad.transcript_source_preparation import TranscriptSourcePreparation
from toad.transcript_state import LiveTranscript, LatestViewportRequest
from toad.widgets.irc_message import IRCMessage, WireMarkdownMessage

HISTORY_PAGE_SIZE = 40
INITIAL_HISTORY_PAGE_SIZE = 8
HISTORY_WINDOW_SIZE = 120
HISTORY_PAGE_BYTES = 256 * 1024


class WireMessageStyle(DeclaredFamily, affix="MessageStyle"):
    @property
    @abstractmethod
    def row_type(self): ...

    @abstractmethod
    def next(self): ...

    def block(self, message, *, direction):
        return self.row_type(message, direction=direction)


class IrcMessageStyle(WireMessageStyle):
    row_type = IRCMessage

    def next(self):
        return MarkdownMessageStyle()


class MarkdownMessageStyle(WireMessageStyle):
    row_type = WireMarkdownMessage

    def next(self):
        return IrcMessageStyle()


class MountedMessageHistory(TranscriptSourcePreparation, ConversationBlock, CategorizedBlock, CategorizedMount, containers.VerticalGroup):
    """Own the real row window, asynchronous page publication and its paint witnesses."""
    def __init__(self, view):
        super().__init__(source_state=LiveTranscript())
        self.view = view
        self.rows: list[tuple[WireMessage, Widget]] = []
        self.has_older = False
        self.has_newer = False
        self.reader: ChannelHistoryReader | None = None
        self.tail_receipt = None
        self.channel_receipts = {}
        self.historical_receipts = {}
        self.ack_inflight = False
        self.style = IrcMessageStyle()

    @property
    def current(self):
        return self.is_attached and self.view.query_ancestor(SessionView).is_current

    def capture_reader_admissions(self) -> tuple:
        # Every retained wire row is already mounted. Its original native
        # window position needs no transcript fragment range to reconstruct.
        return ()

    def restore_reader_admissions(self, admissions) -> None:
        """Retained wire rows have no unmounted local fragment admission."""

    @property
    def message_category(self):
        return None

    @cached_property
    def block_cursor(self):
        return ChildBlockCursor(self)

    def projection_changed(self) -> None:
        for _, widget in self.rows:
            apply_block_filter(widget, self.view.visible_categories)
        self._scroll_changed()


    @property
    def window(self):
        return self.view.window

    @property
    def source_identity(self):
        return self.reader.source if self.reader is not None else None

    @property
    def source_publication_available(self):
        return super().source_publication_available and self.current

    @property
    def checkpoint_available(self):
        return (self.state.accepts_source_work and self.reader is not None
                and not self.reader.source.loading)

    def paging_window(self):
        return (tuple(message.view_key for message, _ in self.rows),
                self.has_older, self.has_newer)

    def report_source_coverage(self):
        self.mark_visible()

    def source_failed(self, error):
        self.view.status = f"Wire error: {error}"


    def compose(self):
        from toad.widgets.comms_chat import HistoryLoading
        yield HistoryLoading("Loading messages…", id="history-loading")

    def on_mount(self):
        self.observe_source()

    async def close_source_reader(self):
        self.tail_receipt = None
        self.channel_receipts.clear()
        self.historical_receipts.clear()
        if self.reader is not None:
            await self.reader.aclose()

    async def paint_receipt(self, receipt):
        # A source read may be working. The original native publication fence,
        # never its I/O admission, controls visible delivery of this receipt.
        async with self.window.history_lock:
            if not self.source_publication_available:
                return
            if self.has_newer:
                await self.remove_children(widget for _, widget in self.rows)
                self.rows.clear()
                self.reader.restart()
            await self._mount_page(MessagePage((receipt,), self.has_older, False), older=False)
            self.window.anchor()
        self._scroll_changed()

    def painted_keys(self) -> tuple[tuple[str, int], ...]:
        if not self.is_attached or not self.current:
            return ()
        return tuple(message.view_key for message, _ in self.viewport(
            AcknowledgementViewport).visible_rows())


    def viewport(self, projection):
        return projection(self.rows, self.view.screen._compositor.visible_widgets,
                          self.view.window.content_region)


    @property
    def follows_tail(self) -> bool:
        return self.window.follows_tail


    async def toggle_style(self) -> None:
        """Re-render only the bounded visible history when switching styles."""
        async with self.window.history_lock:
            self.style = self.style.next()
            records = [message for message, _ in self.rows]
            with self.app.batch_update():
                await self.remove_children(widget for _, widget in self.rows)
                self.rows = [(message, self.view.message_block(message)) for message in records]
                await self.mount(*(widget for _, widget in self.rows))
            self.window.scroll_end(animate=False)

    async def mount_page(self, page: MessagePage, *, older: bool) -> None:
        async with self.window.history_lock:
            await self._mount_page(page, older=older)

    async def _mount_page(self, page: MessagePage, *, older: bool) -> None:
        """Publish under the caller's original native tree transaction."""
        from toad.comms_root import root_is_current
        if (not self.source_publication_available or self.reader is None
                or not root_is_current(self.reader.comms.root)):
            return
        mounted = {message.view_key for message, _ in self.rows}
        pairs = [(message, self.view.message_block(message)) for message in page.messages
                 if message.view_key not in mounted]
        if not pairs:
            if older:
                self.has_older = page.has_older
            else:
                self.has_newer = page.has_newer
            self.view.conversation_kind.remember_page(self, page, older)
            return
        if self.rows:
            anchor, protected = self.window.protect_history(
                (widget for _, widget in self.rows), older=older,
                fallback=self.rows[0 if older else -1][1],
            )
        else:
            anchor, protected = None, set()
        async with self.window.preserve_history(anchor):
            if not self.source_publication_available or not root_is_current(self.reader.comms.root):
                return
            await self.insert_page(page, pairs, older=older, protected=protected)
        self.view.conversation_kind.remember_page(self, page, older)
        self.window.check_follow()

    async def insert_page(
        self, page: MessagePage, pairs: list[tuple[WireMessage, Widget]], *, older: bool,
        protected: set[Widget],
    ) -> None:
        before = self.rows[0][1] if older and self.rows else None
        if pairs:
            await self.mount(*(widget for _, widget in pairs), before=before)

        if older:
            self.rows[0:0] = pairs
            self.has_older = page.has_older
            while len(self.rows) > HISTORY_WINDOW_SIZE:
                if self.rows[-1][1] in protected:
                    break
                _, widget = self.rows.pop()
                await widget.remove()
                self.has_newer = True
        else:
            self.rows.extend(pairs)
            # A send receipt can arrive ahead of the next wire page. Keep one
            # ordered projection when the page later fills in concurrent sends.
            self.rows.sort(key=lambda pair: pair[0].view_order)
            order = {widget: message.view_order for message, widget in self.rows}
            self.sort_children(key=lambda widget: order.get(widget, (2, 0, 0)))
            self.has_newer = page.has_newer
            while len(self.rows) > HISTORY_WINDOW_SIZE:
                if self.rows[0][1] in protected:
                    break
                _, widget = self.rows.pop(0)
                await widget.remove()
                self.has_older = True


    def _check_edges(self) -> None:
        self._check_pending = False
        if not self.checkpoint_available or not self.current or not self.rows:
            return
        geometry = self.screen._compositor.visible_widgets.get(self)
        if geometry is None:
            return
        region, _clip = geometry
        viewport = self.window.content_region
        if not region.overlaps(viewport):
            return
        if self.follows_tail and self.has_newer:
            self._request_page(False)
        elif (self.has_older and region.y >= viewport.y - self.prefetch_distance
              and (not self.window.follows_tail or len(self.rows) < HISTORY_WINDOW_SIZE)):
            self._request_page(True)
        elif self.has_newer and region.bottom <= viewport.bottom + self.prefetch_distance:
            self._request_page(False)

    async def _load_page(self, older: bool) -> None:
        snapshot = self.source_snapshot()
        reader = self.reader
        if reader is None or not self.rows:
            return
        limit = (min(HISTORY_PAGE_SIZE, HISTORY_WINDOW_SIZE - len(self.rows))
                 if older and self.window.follows_tail else HISTORY_PAGE_SIZE)
        if limit <= 0:
            return
        edge = self.rows[0 if older else -1][0].view_cursor
        page = await reader.page(before=edge if older else None,
                                 after=None if older else edge, limit=limit)
        async with self.window.history_lock:
            if snapshot.current(self):
                await self._mount_page(page, older=older)

    async def _publish_latest(self, request: LatestViewportRequest) -> bool:
        reader = self.reader
        if reader is None:
            return False
        reader.restart()
        snapshot = self.source_snapshot()
        read = await reader.read(self.follows_tail)
        if not snapshot.current(self) or not request.current(snapshot.window):
            return False
        return await self.publish(read)

    async def publish(self, read: HistoryReadResult) -> bool:
        """Validate and advance the original source inside native publication."""
        from toad.comms_root import root_is_current
        async with self.window.history_lock:
            reader = self.reader
            if (reader is None or not self.source_publication_available
                    or not root_is_current(reader.comms.root)
                    or not reader.current(read, self.follows_tail)):
                return False
            page = read.page
            if page is not None:
                if read.replace_tail:
                    # Actual receipts newer than the read's original watermark
                    # may already be painted. Keep their native rows, never a
                    # second receipt/seen list, while replacing the older page.
                    retained = [(message, widget) for message, widget in self.rows
                                if not message.view_key[0] and message.seq > read.high_water]
                    retained_widgets = {widget for _, widget in retained}
                    await self.remove_children(widget for _, widget in self.rows
                                               if widget not in retained_widgets)
                    self.rows[:] = retained
                    mounted = {message.view_key for message, _ in retained}
                    self.historical_receipts = {key: source for key, source in self.historical_receipts.items()
                                                if key in mounted}
                    self.channel_receipts = {seq: source for seq, source in self.channel_receipts.items()
                                             if ("", seq) in mounted}
                    self.tail_receipt = None
                    self.has_older = page.has_older
                    await self._mount_page(page, older=False)
                    if loading := self.query_one_optional("#history-loading"):
                        await loading.remove()
                elif page.messages and self.follows_tail:
                    await self._mount_page(page, older=False)
                elif page.messages:
                    self.has_newer = True
            if not reader.current(read, self.follows_tail) or not root_is_current(reader.comms.root):
                return False
            reader.accept(read, read.follow_tail)
            return True

    def mark_visible(self) -> None:
        if self.ack_inflight or not self.is_attached:
            return
        from toad.comms_root import root_is_current

        if self.reader is None or not root_is_current(self.reader.comms.root):
            self.view.display = False
            return
        visible = set(self.painted_keys())
        mounted_keys = {message.view_key for message, _ in self.rows}
        self.historical_receipts = {
            key: source for key, source in self.historical_receipts.items() if key in mounted_keys
        }
        historical = next((page for key, page in self.historical_receipts.items() if key in visible), None)
        if historical is not None:
            selected = {key for key, page in self.historical_receipts.items()
                        if page is historical and key in visible}
            self.ack_inflight = True
            self.view.run_worker(self.mark_historical(historical, selected), group="comms-painted-read")
            return
        painted = {sequence for source, sequence in visible if not source}
        selected = self.view.conversation_kind.painted_page(self, painted)
        if selected is None:
            return
        page, original_page = selected
        self.ack_inflight = True
        self.view.run_worker(self.mark_page(page, original_page), group="comms-painted-read")


    async def mark_historical(self, page: MessagePage, keys: set[tuple[str, int]]) -> None:
        from toad.comms_root import implicit_root, root_is_current, run_selected_write
        try:
            if self.reader is None or not root_is_current(self.reader.comms.root) or not self.current:
                return
            displayed = page.historical_display.select({seq for _, seq in keys})
            await asyncio.to_thread(run_selected_write, self.reader.comms.root,
                self.reader.comms.views.mark_historical_view_read, displayed, implicit=implicit_root())
            for key in keys:
                if self.historical_receipts.get(key) is page:
                    del self.historical_receipts[key]
        except ValueError:
            self.historical_receipts.clear()
        finally:
            self.ack_inflight = False


    async def mark_page(self, page: MessagePage, original_page: MessagePage | None = None) -> None:
        try:
            from toad.comms_root import root_is_current

            if self.reader is None or not self.is_attached or not self.current:
                return
            comms = self.reader.comms
            if not root_is_current(comms.root):
                self.view.display = False
                return
            project = str(self.view.project_path)
            target = self.view.target
            await self.view.conversation_kind.mark_painted(comms, target, project, page)
            if self.tail_receipt is page or self.tail_receipt is original_page:
                self.tail_receipt = None
            if original_page is not None:
                for message in page.messages:
                    if self.channel_receipts.get(message.seq) is original_page:
                        del self.channel_receipts[message.seq]
        except ValueError:
            # The peer, viewer, channel scope, or bus changed after page
            # fetch. Discard mounted history and fetch the current projection.
            if self.is_attached:
                async with self.window.history_lock:
                    await self.remove_children(widget for _, widget in self.rows)
                    self.rows.clear()
                    self.reader.restart()
                    self.has_older = False
                    self.has_newer = False
            self.tail_receipt = None
            self.channel_receipts.clear()
        finally:
            self.ack_inflight = False
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
