"""Bounded mounted wire-message publication and displayed-only read receipts."""
from __future__ import annotations
import asyncio
from abc import abstractmethod
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from agent_comms.message_page import MessagePage
from agent_comms.messages import Message as WireMessage
from textual import containers
from textual.widget import Widget
from toad.message_viewport import AcknowledgementViewport
from toad.channel_preparation import HistoryReadRequest, HistoryReadResult
from toad.screens.session_view import SessionView
from toad.widgets.irc_message import IRCMessage, WireMarkdownMessage

HISTORY_PAGE_SIZE = 40
INITIAL_HISTORY_PAGE_SIZE = 8
HISTORY_WINDOW_SIZE = 120
HISTORY_PAGE_BYTES = 256 * 1024
HISTORY_EDGE_THRESHOLD = 2


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


class MountedMessageHistory:
    """Own the real row window, asynchronous page publication and its paint witnesses."""
    def __init__(self, view):
        self.view = view
        self.rows: list[tuple[WireMessage, Widget]] = []
        self.has_older = False
        self.has_newer = False
        self.initialized = False
        self.poll_cursor = 0
        self.edge_scheduled = False
        self.edge_on_resume = False
        self.lock = asyncio.Lock()
        self.service = None
        self.revision = None
        self.display_identity = None
        self.tail_receipt = None
        self.channel_receipts = {}
        self.historical_receipts = {}
        self.ack_inflight = False
        self.style = IrcMessageStyle()

    @property
    def attached(self):
        return self.view.is_attached

    @property
    def current(self):
        return self.attached and self.view.query_ancestor(SessionView).is_current

    def block(self, message):
        return self.view.message_block(message)

    def capture_reader_admissions(self) -> tuple:
        # Every retained wire row is already mounted. Its original native
        # window position needs no transcript fragment range to reconstruct.
        return ()

    def restore_reader_admissions(self, admissions) -> None:
        """Retained wire rows have no unmounted local fragment admission."""

    def projection_changed(self) -> None:
        """Wire history has no native transcript-category projection."""

    def retire(self):
        self.tail_receipt = None
        self.channel_receipts.clear()
        self.historical_receipts.clear()

    async def paint_receipt(self, receipt):
        async with self.lock:
            if self.has_newer:
                await self.view.contents.remove_children(widget for _, widget in self.rows)
                self.rows.clear()
                self.initialized = False
            await self.mount_page(MessagePage((receipt,), self.has_older, False), older=False)
            self.view.window.anchor()
        self.revision = None

    def read_page(
        self,
        comms,
        *,
        before: int | None = None,
        after: int | None = None,
        limit: int = HISTORY_PAGE_SIZE,
    ) -> MessagePage:
        return self.view.conversation_kind.page(
            comms, self.view.target, worktree=str(self.view.project_path),
            before=before, after=after, limit=limit, max_bytes=HISTORY_PAGE_BYTES,
        )


    def painted_keys(self) -> tuple[tuple[str, int], ...]:
        if not self.attached or not self.current:
            return ()
        return tuple(message.view_key for message, _ in self.viewport(
            AcknowledgementViewport).visible_rows())


    def viewport(self, projection):
        return projection(self.rows, self.view.screen._compositor.visible_widgets,
                          self.view.window.content_region)


    def request(self) -> HistoryReadRequest:
        assert self.service is not None
        return HistoryReadRequest(
            self.service, self.view.conversation_kind, self.view.target, Path(self.view.project_path),
            self.initialized, self.poll_cursor,
            not self.has_newer and self.view.window.follows_tail, self.revision,
            INITIAL_HISTORY_PAGE_SIZE, HISTORY_PAGE_SIZE, HISTORY_PAGE_BYTES,
            self.display_identity,
        )


    async def toggle_style(self) -> None:
        """Re-render only the bounded visible history when switching styles."""
        async with self.lock:
            self.style = self.style.next()
            records = [message for message, _ in self.rows]
            with self.view.app.batch_update():
                await self.view.contents.remove_children(
                    widget for _, widget in self.rows
                )
                self.rows = [
                    (message, self.block(message)) for message in records
                ]
                await self.view.contents.mount(
                    *(widget for _, widget in self.rows),
                    before=self.view.query_one("#comms-activity"),
                )
            self.view.window.scroll_end(animate=False)


    async def mount_page(self, page: MessagePage, *, older: bool) -> None:
        from toad.comms_root import root_is_current

        if self.service is None or not root_is_current(self.service.root):
            self.view.display = False
            return
        mounted = {message.view_key for message, _ in self.rows}
        records = [message for message in page.messages if message.view_key not in mounted]
        if not records:
            self.view.conversation_kind.remember_page(self, page, older)
            if older:
                self.has_older = page.has_older
            else:
                self.has_newer = page.has_newer
            return

        pairs = [(message, self.block(message)) for message in records]
        async with self.view.window.history_lock:
            if not root_is_current(self.service.root):
                self.view.display = False
                return
            anchor = self.rows[0 if older else -1][1] if self.rows else None
            async with self.view.window.preserve_history(anchor):
                if not root_is_current(self.service.root):
                    self.view.display = False
                    return
                await self.insert_page(page, pairs, older=older)
        self.view.conversation_kind.remember_page(self, page, older)
        self.view.window.check_follow()


    async def insert_page(
        self, page: MessagePage, pairs: list[tuple[WireMessage, Widget]], *, older: bool,
    ) -> None:
        tray = self.view.query_one("#comms-activity", containers.VerticalGroup)
        before = self.rows[0][1] if older and self.rows else tray
        await self.view.contents.mount(*(widget for _, widget in pairs), before=before)

        if older:
            self.rows[0:0] = pairs
            self.has_older = page.has_older
            while len(self.rows) > HISTORY_WINDOW_SIZE:
                _, widget = self.rows.pop()
                await widget.remove()
                self.has_newer = True
        else:
            self.rows.extend(pairs)
            # A send receipt can arrive ahead of the next wire page. Keep one
            # ordered projection when the page later fills in concurrent sends.
            self.rows.sort(key=lambda pair: pair[0].view_order)
            order = {widget: message.view_order for message, widget in self.rows}
            self.view.contents.sort_children(key=lambda widget: order.get(widget, (2, 0, 0)))
            self.has_newer = page.has_newer
            while len(self.rows) > HISTORY_WINDOW_SIZE:
                _, widget = self.rows.pop(0)
                await widget.remove()
                self.has_older = True


    def on_scroll(self, _scroll_y: float = 0) -> None:
        if not self.attached:
            return
        if not self.current:
            self.edge_on_resume = True
            return
        self.edge_on_resume = False
        if not self.initialized or not self.rows or self.edge_scheduled:
            return
        scroll_y = self.view.window.scroll_y
        follows_tail = self.view.window.follows_tail
        near_top = (
            scroll_y <= HISTORY_EDGE_THRESHOLD and self.has_older
            and (not follows_tail or
                 (self.view.window.max_scroll_y == 0 and len(self.rows) < HISTORY_WINDOW_SIZE))
        )
        near_bottom = (
            self.view.window.max_scroll_y - scroll_y <= HISTORY_EDGE_THRESHOLD
            and self.has_newer
        )
        if near_top or near_bottom:
            self.edge_scheduled = True
            # One owned waiter may suspend behind a refresh without holding the
            # widget message pump. Returning/rearming while the lock is held
            # otherwise creates a tight after-refresh callback loop.
            self.view.run_worker(self.load_edge(), group="comms-history-edge")


    async def load_edge(self) -> None:
        progressed = False
        try:
            async with self.lock:
                if not self.attached:
                    return
                if not self.current:
                    self.edge_on_resume = True
                    return
                if not self.rows:
                    return
                from toad.comms_root import root_is_current

                comms = self.service
                if comms is None or not root_is_current(comms.root):
                    self.view.display = False
                    return
                before = (self.rows[0][0].view_cursor, self.rows[-1][0].view_cursor,
                          self.has_older, self.has_newer)
                route = (self.view.target, self.view.kind, self.view.project_path)
                older: bool
                if self.view.window.scroll_y <= HISTORY_EDGE_THRESHOLD and self.has_older:
                    limit = (min(HISTORY_PAGE_SIZE, HISTORY_WINDOW_SIZE - len(self.rows))
                              if self.view.window.follows_tail else HISTORY_PAGE_SIZE)
                    if limit <= 0:
                        return
                    older = True
                    page = await asyncio.to_thread(self.read_page, comms, before=self.rows[0][0].view_cursor, limit=limit)
                elif (
                    self.view.window.max_scroll_y - self.view.window.scroll_y
                    <= HISTORY_EDGE_THRESHOLD
                    and self.has_newer
                ):
                    older = False
                    page = await asyncio.to_thread(self.read_page, comms, after=self.rows[-1][0].view_cursor)
                else:
                    return
                if not self.attached:
                    return
                if (not self.current or self.service is not comms
                        or route != (self.view.target, self.view.kind, self.view.project_path)):
                    self.edge_on_resume = True
                    return
                if not root_is_current(comms.root):
                    self.view.display = False
                    return
                await self.mount_page(page, older=older)
                after = (self.rows[0][0].view_cursor, self.rows[-1][0].view_cursor,
                         self.has_older, self.has_newer)
                progressed = before != after
        except Exception as error:
            self.view.status = f"Wire error: {error}"
        finally:
            self.edge_scheduled = False
            # Fill an underfull viewport after real progress, but do not spin
            # on empty/duplicate pages or failures. New scroll/source events
            # may request another attempt through the ordinary paths.
            if progressed and self.attached:
                self.view.call_after_refresh(self.on_scroll)


    async def publish(self, read: HistoryReadResult) -> bool:
        """Refresh the bounded history window; return whether to follow the end."""
        follow = not self.has_newer and self.view.window.follows_tail
        high_water = read.high_water
        if not self.initialized:
            page = read.page
            assert page is not None
            await self.mount_page(page, older=False)
            if loading := self.view.query_one_optional("#history-loading"):
                await loading.remove()
            self.has_older = page.has_older
            self.display_identity = self.view.conversation_kind.display_identity(page)
            self.initialized = True
            self.poll_cursor = high_water
            self.view.call_after_refresh(self.on_scroll)
            return True

        page = read.page
        if read.replace_tail:
            assert page is not None
            self.tail_receipt = None
            self.channel_receipts.clear()
            await self.view.contents.remove_children(widget for _, widget in self.rows)
            self.rows.clear()
            self.has_older = page.has_older
            self.has_newer = False
            await self.mount_page(page, older=False)
            self.display_identity = self.view.conversation_kind.display_identity(page)
            self.poll_cursor = (page.newest_seq if page.has_newer else high_water) or high_water
            return True
        if high_water <= self.poll_cursor:
            return follow
        if page is None:
            return follow
        self.display_identity = self.view.conversation_kind.display_identity(page)
        follow = not self.has_newer and self.view.window.follows_tail
        if page.messages and follow:
            await self.mount_page(page, older=False)
            self.poll_cursor = (page.newest_seq if page.has_newer else high_water) or high_water
        else:
            if page.messages:
                self.has_newer = True
            self.poll_cursor = high_water
        return follow


    def mark_visible(self) -> None:
        if self.ack_inflight or not self.attached:
            return
        from toad.comms_root import root_is_current

        if self.service is None or not root_is_current(self.service.root):
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
            if self.service is None or not root_is_current(self.service.root) or not self.current:
                return
            displayed = page.historical_display.select({seq for _, seq in keys})
            await asyncio.to_thread(run_selected_write, self.service.root,
                self.service.views.mark_historical_view_read, displayed, implicit=implicit_root())
            for key in keys:
                if self.historical_receipts.get(key) is page:
                    del self.historical_receipts[key]
        except ValueError:
            self.historical_receipts.clear()
        finally:
            self.ack_inflight = False


    async def mark_page(self, page: MessagePage, original_page: MessagePage | None = None) -> None:
        try:
            comms = self.service
            from toad.comms_root import root_is_current

            if comms is None or not self.attached or not self.current:
                return
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
            if self.attached:
                async with self.lock:
                    await self.view.contents.remove_children(widget for _, widget in self.rows)
                    self.rows.clear()
                    self.initialized = False
                    self.poll_cursor = 0
                    self.revision = None
                    self.display_identity = None
                    self.has_older = False
                    self.has_newer = False
            self.tail_receipt = None
            self.channel_receipts.clear()
        finally:
            self.ack_inflight = False
            if self.attached:
                self.view.call_after_refresh(self.mark_visible)
