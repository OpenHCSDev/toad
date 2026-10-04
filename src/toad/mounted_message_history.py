"""Bounded mounted wire-message publication and displayed-only read receipts."""
from __future__ import annotations
import asyncio
from abc import abstractmethod
from functools import cached_property
from contextlib import AsyncExitStack, asynccontextmanager
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
from toad.transcript_source_preparation import HistorySourceSnapshot, TranscriptSourcePreparation
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

    @asynccontextmanager
    async def native_publication(
        self, retained: tuple[tuple[WireMessage, Widget], ...], *, older: bool = False,
    ):
        """Own one row mutation and reader compensation through the original window."""
        window = self.window
        if retained:
            anchor, protected = window.protect_history(
                (widget for _, widget in retained), older=older,
                fallback=retained[0 if older else -1][1],
            )
        else:
            anchor, protected = None, set()
        async with window.preserve_history(anchor):
            yield protected
        window.check_follow()

    async def paint_receipt(self, receipt):
        # A source read may be working. The original native publication fence,
        # never its I/O admission, controls visible delivery of this receipt.
        async with self.window.history_lock:
            if not self.source_publication_available:
                return
            retained = () if self.has_newer else tuple(self.rows)
            if self.has_newer:
                self.reader.restart()
            await self._mount_page(MessagePage((receipt,), self.has_older, False),
                                   older=False, retained=retained, style=self.style)
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
        """Publish one style request on this history's original worker lifetime."""
        async with self.window.history_lock:
            if not self.source_publication_available:
                return
            style = self.style.next()
            if not self.rows:
                self.style = style
                return
            await self._mount_page(None, older=False, retained=(), style=style)
        self.window.scroll_end(animate=False)

    async def mount_page(self, page: MessagePage, *, older: bool) -> None:
        async with self.window.history_lock:
            await self._mount_page(page, older=older,
                                   retained=tuple(self.rows), style=self.style)

    async def _mount_page(
        self, page: MessagePage | None, *, older: bool,
        retained: tuple[tuple[WireMessage, Widget], ...], style: WireMessageStyle,
        read: HistoryReadResult | None = None,
    ) -> None:
        """Acquire reader/native resources only for an actual row mutation."""
        from toad.comms_root import root_is_current
        snapshot = self.source_snapshot()
        if (not snapshot.current(self) or self.reader is None
                or not root_is_current(self.reader.comms.root)):
            return
        mounted = {message.view_key for message, _ in retained}
        messages = (tuple(message for message, _ in self.rows)
                    if page is None else page.messages)
        pairs = [(message, self.view.message_block(message, style=style))
                 for message in messages if message.view_key not in mounted]
        retained_widgets = {widget for _, widget in retained}
        removed = tuple(widget for _, widget in self.rows if widget not in retained_widgets)
        if pairs or removed:
            async with self.native_publication(retained, older=older) as protected:
                if (not snapshot.current(self)
                        or not root_is_current(self.reader.comms.root)):
                    return
                committed = await self.insert_page(
                    page, pairs, older=older, protected=protected,
                    retained=retained, removed=removed, style=style,
                    snapshot=snapshot, read=read)
            if not committed:
                return
            # Native AwaitRemove already owns completion and error delivery.
            # A committed source must not wait for an old row's Unmount.
        else:
            if page is not None:
                if read is not None and read.replace_tail:
                    self.has_older = page.has_older
                if older:
                    self.has_older = page.has_older
                else:
                    self.has_newer = page.has_newer
            self.view.conversation_kind.remember_page(self, page, older)

    async def insert_page(
        self, page: MessagePage | None, pairs: list[tuple[WireMessage, Widget]], *, older: bool,
        protected: set[Widget], retained: tuple[tuple[WireMessage, Widget], ...],
        removed: tuple[Widget, ...], style: WireMessageStyle,
        snapshot: HistorySourceSnapshot,
        read: HistoryReadResult | None,
    ) -> bool:
        # New rows remain acquisition resources until their original native
        # mount completes. Cancellation retires them before the fence opens;
        # the previous committed row association is still intact.
        before = retained[0][1] if older and retained else None
        async with AsyncExitStack() as admission:
            if pairs:
                admission.push_async_callback(self.remove_children,
                                              tuple(widget for _, widget in pairs))
                await self.mount(*(widget for _, widget in pairs), before=before)
            from toad.comms_root import root_is_current
            if not snapshot.current(self) or not root_is_current(self.reader.comms.root):
                return False
            if read is not None and not self.reader.current(read, self.follows_tail):
                return False
            self.rows[:] = (*pairs, *retained) if older else (*retained, *pairs)
            self.style = style
            if read is not None and read.replace_tail:
                self.has_older = page.has_older
            if older:
                if page is not None:
                    self.has_older = page.has_older
                edge = -1
            else:
                self.rows.sort(key=lambda pair: pair[0].view_order)
                order = {widget: message.view_order for message, widget in self.rows}
                self.sort_children(key=lambda widget: order.get(widget, (2, 0, 0)))
                if page is not None:
                    self.has_newer = page.has_newer
                edge = 0
            # Native prune retires the old scene synchronously. Transfer the
            # complete row association/order before awaiting its completion.
            admission.pop_all()
        retired = list(removed)
        while len(self.rows) > HISTORY_WINDOW_SIZE:
            if self.rows[edge][1] in protected:
                break
            _, widget = self.rows.pop(edge)
            if older:
                self.has_newer = True
            else:
                self.has_older = True
            retired.append(widget)
        self.view.conversation_kind.remember_page(self, page, older)
        self.remove_children(retired)
        return True


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
                await self._mount_page(page, older=older,
                                       retained=tuple(self.rows), style=self.style)

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
            snapshot = self.source_snapshot()
            page = read.page
            if page is not None:
                if read.replace_tail:
                    # Actual receipts newer than the read's original watermark
                    # may already be painted. Keep their native rows, never a
                    # second receipt/seen list, while replacing the older page.
                    retained = tuple((message, widget) for message, widget in self.rows
                                     if not message.view_key[0] and message.seq > read.high_water)
                    await self._mount_page(page, older=False,
                                           retained=retained, style=self.style, read=read)
                elif page.messages and self.follows_tail:
                    await self._mount_page(page, older=False,
                                           retained=tuple(self.rows), style=self.style, read=read)
                elif page.messages:
                    self.has_newer = True
            if (not snapshot.current(self) or not reader.current(read, self.follows_tail)
                    or not root_is_current(reader.comms.root)):
                return False
            reader.accept(read, read.follow_tail)
            if page is not None and read.replace_tail:
                if loading := self.query_one_optional("#history-loading"):
                    loading.remove()
            return True

    def mark_visible(self) -> None:
        if self.ack_inflight or not self.is_attached:
            return
        from toad.comms_root import root_is_current

        if self.reader is None or not root_is_current(self.reader.comms.root):
            self.view.display = False
            return
        visible = set(self.painted_keys())
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
        self.view.run_worker(self.mark_page(page, original_page,
                            snapshot=self.source_snapshot()), group="comms-painted-read")


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
            self.historical_receipts = {
                key: source for key, source in self.historical_receipts.items() if source is not page
            }
        finally:
            self.ack_inflight = False


    async def mark_page(
        self, page: MessagePage, original_page: MessagePage | None, *,
        snapshot: HistorySourceSnapshot,
    ) -> None:
        try:
            from toad.comms_root import root_is_current

            if self.reader is None or not snapshot.current(self):
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
            if snapshot.current(self):
                async with self.window.history_lock:
                    async with self.native_publication(()):
                        if not snapshot.current(self):
                            return
                        self.remove_children(tuple(widget for _, widget in self.rows))
                        self.rows.clear()
                        self.reader.restart()
                        self.has_older = False
                        self.has_newer = False
                        self.tail_receipt = None
                        self.channel_receipts.clear()
                        self.historical_receipts.clear()
        finally:
            self.ack_inflight = False
            if self.is_attached:
                self.view.call_after_refresh(self.mark_visible)
