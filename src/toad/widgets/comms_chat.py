"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agent_comms import Comms, MessagePage, OBSERVATION_INTERVAL, ThreadRole, WireRevision
from agent_comms import Message as WireMessage
from agent_comms.operations import wire
from textual import containers, work
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static
from textual.widget import Widget

from toad import messages
from toad.constants import ALL_COMMS_TARGET
from toad.channel_preparation import (
    HistoryKind, HistoryReadRequest, HistoryReadResult, display_identity,
)
from toad.widgets.conversation import (
    Contents,
    ContentsGrid,
    Conversation,
    Cursor,
    CursorContainer,
    Window,
)
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.widgets.throbber import Throbber
from toad.widgets.irc_message import IRCMessage, MembershipNotice, WireMarkdownMessage
from toad.widgets.channel_participants import ChannelParticipants
from toad.widgets.channel_prompt import ChannelPrompt

HISTORY_PAGE_SIZE = 40
INITIAL_HISTORY_PAGE_SIZE = 8
HISTORY_WINDOW_SIZE = 120
HISTORY_PAGE_BYTES = 256 * 1024
HISTORY_EDGE_THRESHOLD = 2


def _comms_root() -> Path:
    from toad.comms_root import current_root

    return current_root()


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-")
        or "session"
    )


def resolve_session_thread(
    comms, project_path: Path, preferred: str | None = None
) -> str | None:
    """Resolve Toad's wire identity from the registry's authoritative worktree."""
    project = Path(project_path).expanduser().resolve()
    threads = comms.registry.all_threads()
    if preferred:
        preferred = comms.registry.canonical_name(preferred)
    if (
        preferred in threads
        and Path(threads[preferred].worktree).expanduser().resolve() == project
    ):
        return preferred
    matches = [
        name
        for name, thread in threads.items()
        if Path(thread.worktree).expanduser().resolve() == project
        and "acp" in thread.tags
    ]
    if len(matches) == 1:
        return matches[0]
    return None


class CommsChatView(Conversation):
    """A wire-backed conversation using Toad's normal transcript primitives."""

    BINDINGS = Conversation.BINDINGS[:5]

    def __init__(
        self,
        project_path: Path,
        *,
        target: str,
        kind: str,
        me: str,
        wire_root: str | None = None,
    ) -> None:
        super().__init__(project_path)
        self.target = target
        self.kind = kind
        self._me = me
        self._unknown_send: tuple[str, int, str] | None = None
        self._human_admission_blocked = False
        self._send_block_reason = ""
        self._bound_root = Path(wire_root).resolve() if wire_root is not None else None
        self.set_prompt_history_scope(f"comms:{kind}:{target}")
        self._history: list[tuple[WireMessage, Widget]] = []
        self._has_older = False
        self._has_newer = False
        self._history_initialized = False
        self._poll_cursor = 0
        self._edge_load_scheduled = False
        self._edge_check_on_resume = False
        self._refresh_lock = asyncio.Lock()
        # This widget is constructed during screen composition; the App's
        # revision-aware reader becomes available when the view mounts.
        self._wire: Comms | None = None
        self._revision: WireRevision | None = None
        self._display_identity: tuple | None = None
        self._prepared_history: HistoryReadResult | None = None
        self._history_warm_task: asyncio.Task[HistoryReadResult] | None = None
        self._history_warm_request: HistoryReadRequest | None = None
        self._ack_page: MessagePage | None = None
        self._channel_ack_pages: dict[int, MessagePage] = {}
        self._ack_inflight = False
        self.irc_style = True

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                with CursorContainer(id="cursor-container"):
                    yield Cursor()
                with Contents(id="contents"):
                    yield Static("Loading messages…", id="history-loading")
                    yield containers.VerticalGroup(id="comms-activity")
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            if self.kind != "dm":
                yield ChannelParticipants()
            yield Throbber(id="throbber")
            prompt_type = ChannelPrompt if self.kind != "dm" else Prompt
            yield prompt_type(
                simple_input=True,
                placeholder=(
                    "Message #all (broadcast)"
                    if self.kind == "irc"
                    else f"Message {self.target}"
                ),
            ).data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent_ready=Conversation.agent_ready,
                current_mode=Conversation.current_mode,
                modes=Conversation.modes,
                status=Conversation.status,
            )

    async def initialize_view(self) -> None:
        # Reuse the canonical core service already shared by tab sidebars and
        # transcript readers. Its revision-aware caches remain model-owned.
        try:
            root = _comms_root().resolve()
        except (OSError, ValueError, RuntimeError):
            self.display = False
            return
        if self._bound_root is not None and root != self._bound_root:
            self.display = False
            return
        self._wire = (self.app.coordination_wire if root == self.app.coordination_wire.root
                      else wire(root))
        self.agent_info = Content(self._target_label())
        self.agent_ready = True
        self.prepare_prompt()
        self.window.anchor()
        self.watch(self.window, "scroll_y", self._on_window_scroll, init=False)
        self.set_interval(OBSERVATION_INTERVAL, self._refresh)
        # CommsScreen has already presented its route before mounting this
        # view. Start its asynchronous page read now, overlapping it with the
        # remaining control mounts rather than waiting for another empty
        # history frame. _refresh_lock still serializes page mutations.
        self.run_worker(self._refresh(), group="comms-initial-history")

    def prepare_prompt(self) -> None:
        """Apply comms prompt state after a mode becomes active."""
        prompt = self.query_one_optional(Prompt)
        if prompt is None:
            # A large Channels panel may mount its virtual rows before the
            # channel composer finishes composing its Prompt. Both its Mount
            # callback and the containing Screen's Mount callback can arrive
            # first; settle once after the committed first layout instead of
            # dereferencing an unmounted getter.
            if self.is_attached:
                self.call_after_refresh(self.prepare_prompt)
            return
        prompt.agent_info = self.agent_info
        prompt.agent_ready = True
        prompt.shell_mode = False
        prompt.update_prompt()
        prompt.focus()

    def watch_agent(self, agent) -> None:
        """Keep the inherited agent reactive from turning this into a shell session."""
        self.agent_info = Content(self._target_label())

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        """Comms readiness has no shell process to await."""

    def _target_label(self) -> str:
        if self.kind == "irc":
            return f"{ALL_COMMS_TARGET} · all comms"
        if self.kind == "dm":
            return f"@{self.target}"
        return self.target

    def _message_page(
        self,
        comms,
        *,
        before: int | None = None,
        after: int | None = None,
        limit: int = HISTORY_PAGE_SIZE,
    ) -> MessagePage:
        if self.kind == "dm":
            return comms.dm_display_page(
                self.target,
                worktree=str(self.project_path),
                before=before,
                after=after,
                limit=limit,
                max_bytes=HISTORY_PAGE_BYTES,
            )
        return comms.channel_display_page(
            self.target,
            worktree=str(self.project_path),
            before=before,
            after=after,
            limit=limit,
            max_bytes=HISTORY_PAGE_BYTES,
        )

    def _message_block(self, message: WireMessage) -> Widget:
        if message.membership is not None:
            return MembershipNotice(message)
        direction = ("User" if message.sender_role is ThreadRole.USER else
                     "Outbound" if message.sender == self._me else "Inbound")
        if self.irc_style:
            return IRCMessage(message, direction=direction)
        return WireMarkdownMessage(message, direction=direction)

    def _painted_message_sequences(self) -> tuple[int, ...]:
        """Rows in the committed viewport, adapted from the sidebar worktree."""
        if not self.is_attached or not self.screen.is_active:
            return ()
        geometry = self.screen._compositor.visible_widgets
        viewport = self.window.content_region
        visible: list[int] = []
        for message, widget in self._history:
            painted = (
                widget.read_ack_widget()
                if isinstance(widget, (IRCMessage, WireMarkdownMessage)) else widget
            )
            placement = geometry.get(painted)
            if placement is None:
                continue
            region, clip = placement
            if (
                region.overlaps(viewport)
                and region.overlaps(clip)
                and clip.overlaps(viewport)
            ):
                visible.append(message.seq)
        return tuple(visible)

    def _history_request(self) -> HistoryReadRequest:
        assert self._wire is not None
        return HistoryReadRequest(
            self._wire, HistoryKind(self.kind), self.target, Path(self.project_path),
            self._history_initialized, self._poll_cursor,
            not self._has_newer and self.window.follows_tail, self._revision,
            INITIAL_HISTORY_PAGE_SIZE, HISTORY_PAGE_SIZE, HISTORY_PAGE_BYTES,
            self._display_identity,
        )

    def _warm_history(self) -> None:
        if self._history_warm_task is not None and not self._history_warm_task.done():
            return
        request = self._history_request()
        self._history_warm_request = request
        self._history_warm_task = asyncio.create_task(
            self.app.channel_history_reader.read(request, self._prepared_history, background=True),
            name="warm-channel-history",
        )
        self._history_warm_task.add_done_callback(self._history_warmed)

    def _history_warmed(self, task: asyncio.Task[HistoryReadResult]) -> None:
        if task.cancelled():
            return
        try:
            result = task.result()
        except Exception:
            # Active loading reports failures through the existing visible path.
            return
        if (
            self.is_attached
            and self.query_one_optional(Window) is not None
            and result.request == self._history_request()
        ):
            self._prepared_history = result

    async def _read_history(self) -> HistoryReadResult:
        request = self._history_request()
        prepared = self._prepared_history
        if prepared is not None and prepared.request == request:
            self._prepared_history = None
            if self._history_warm_task is not None and self._history_warm_task.done():
                self._history_warm_task = None
                self._history_warm_request = None
            return prepared
        warming = self._history_warm_task
        if warming is not None and self._history_warm_request == request:
            self._history_warm_task = None
            await asyncio.wait((warming,))
            return warming.result()
        return await self.app.channel_history_reader.read(request)

    async def on_unmount(self) -> None:
        self._ack_page = None
        self._channel_ack_pages.clear()
        if self._history_warm_task is not None:
            task = self._history_warm_task
            task.cancel()
            self._history_warm_task = None
            await asyncio.gather(task, return_exceptions=True)
        self._history_warm_request = None
        self._prepared_history = None

    async def toggle_message_style(self) -> None:
        """Re-render only the bounded visible history when switching styles."""
        async with self._refresh_lock:
            self.irc_style = not self.irc_style
            records = [message for message, _ in self._history]
            with self.app.batch_update():
                await self.contents.remove_children(
                    widget for _, widget in self._history
                )
                self._history = [
                    (message, self._message_block(message)) for message in records
                ]
                await self.contents.mount(
                    *(widget for _, widget in self._history),
                    before=self.query_one("#comms-activity"),
                )
            self.window.scroll_end(animate=False)

    async def _mount_page(self, page: MessagePage, *, older: bool) -> None:
        from toad.comms_root import root_is_current

        if self._wire is None or not root_is_current(self._wire.root):
            self.display = False
            return
        if self.kind != "dm":
            self._channel_ack_pages.update((message.seq, page) for message in page.messages)
        elif not older and page.messages:
            self._ack_page = page
        mounted = {message.seq for message, _ in self._history}
        records = [message for message in page.messages if message.seq not in mounted]
        if not records:
            if older:
                self._has_older = page.has_older
            else:
                self._has_newer = page.has_newer
            return

        pairs = [(message, self._message_block(message)) for message in records]
        async with self.window.history_lock:
            if not root_is_current(self._wire.root):
                self.display = False
                return
            anchor = self._history[0 if older else -1][1] if self._history else None
            async with self.window.preserve_history(anchor):
                if not root_is_current(self._wire.root):
                    self.display = False
                    return
                with self.app.batch_update():
                    await self._insert_page(page, pairs, older=older)
        self.window.check_follow()

    async def _insert_page(
        self, page: MessagePage, pairs: list[tuple[WireMessage, Widget]], *, older: bool,
    ) -> None:
        tray = self.query_one("#comms-activity", containers.VerticalGroup)
        before = self._history[0][1] if older and self._history else tray
        await self.contents.mount(*(widget for _, widget in pairs), before=before)

        if older:
            self._history[0:0] = pairs
            self._has_older = page.has_older
            while len(self._history) > HISTORY_WINDOW_SIZE:
                _, widget = self._history.pop()
                await widget.remove()
                self._has_newer = True
        else:
            self._history.extend(pairs)
            # A send receipt can arrive ahead of the next wire page. Keep one
            # ordered projection when the page later fills in concurrent sends.
            self._history.sort(key=lambda pair: pair[0].seq)
            order = {widget: message.seq for message, widget in self._history}
            self.contents.sort_children(key=lambda widget: order.get(widget, float("inf")))
            self._has_newer = page.has_newer
            while len(self._history) > HISTORY_WINDOW_SIZE:
                _, widget = self._history.pop(0)
                await widget.remove()
                self._has_older = True

    def _on_window_scroll(self, _scroll_y: float = 0) -> None:
        if not self.is_attached:
            return
        if not self.screen.is_current:
            self._edge_check_on_resume = True
            return
        self._edge_check_on_resume = False
        if not self._history_initialized or not self._history or self._edge_load_scheduled:
            return
        scroll_y = self.window.scroll_y
        near_top = (
            scroll_y <= HISTORY_EDGE_THRESHOLD and self._has_older
            and (not self.window.follows_tail or
                 (self.window.max_scroll_y == 0 and len(self._history) < HISTORY_WINDOW_SIZE))
        )
        near_bottom = (
            self.window.max_scroll_y - scroll_y <= HISTORY_EDGE_THRESHOLD
            and self._has_newer
        )
        if near_top or near_bottom:
            self._edge_load_scheduled = True
            # One owned waiter may suspend behind a refresh without holding the
            # widget message pump. Returning/rearming while the lock is held
            # otherwise creates a tight after-refresh callback loop.
            self.run_worker(self._load_history_edge(), group="comms-history-edge")

    async def _load_history_edge(self) -> None:
        progressed = False
        try:
            async with self._refresh_lock:
                if not self.is_attached:
                    return
                if not self.screen.is_current:
                    self._edge_check_on_resume = True
                    return
                if not self._history:
                    return
                from toad.comms_root import root_is_current

                comms = self._wire
                if comms is None or not root_is_current(comms.root):
                    self.display = False
                    return
                before = (self._history[0][0].seq, self._history[-1][0].seq,
                          self._has_older, self._has_newer)
                route = (self.target, self.kind, self.project_path)
                older: bool
                if self.window.scroll_y <= HISTORY_EDGE_THRESHOLD and self._has_older:
                    limit = (min(HISTORY_PAGE_SIZE, HISTORY_WINDOW_SIZE - len(self._history))
                              if self.window.follows_tail else HISTORY_PAGE_SIZE)
                    if limit <= 0:
                        return
                    older = True
                    page = await asyncio.to_thread(self._message_page, comms, before=self._history[0][0].seq, limit=limit)
                elif (
                    self.window.max_scroll_y - self.window.scroll_y
                    <= HISTORY_EDGE_THRESHOLD
                    and self._has_newer
                ):
                    older = False
                    page = await asyncio.to_thread(self._message_page, comms, after=self._history[-1][0].seq)
                else:
                    return
                if not self.is_attached:
                    return
                if (not self.screen.is_current or self._wire is not comms
                        or route != (self.target, self.kind, self.project_path)):
                    self._edge_check_on_resume = True
                    return
                if not root_is_current(comms.root):
                    self.display = False
                    return
                await self._mount_page(page, older=older)
                after = (self._history[0][0].seq, self._history[-1][0].seq,
                         self._has_older, self._has_newer)
                progressed = before != after
        except Exception as error:
            self.status = f"Wire error: {error}"
        finally:
            self._edge_load_scheduled = False
            # Fill an underfull viewport after real progress, but do not spin
            # on empty/duplicate pages or failures. New scroll/source events
            # may request another attempt through the ordinary paths.
            if progressed and self.is_attached:
                self.call_after_refresh(self._on_window_scroll)

    async def _refresh_history(self, read: HistoryReadResult) -> bool:
        """Refresh the bounded history window; return whether to follow the end."""
        follow = not self._has_newer and self.window.follows_tail
        high_water = read.high_water
        if not self._history_initialized:
            page = read.page
            assert page is not None
            await self._mount_page(page, older=False)
            if loading := self.query_one_optional("#history-loading"):
                await loading.remove()
            self._has_older = page.has_older
            self._display_identity = display_identity(HistoryKind(self.kind), page)
            self._history_initialized = True
            self._poll_cursor = high_water
            self.call_after_refresh(self._on_window_scroll)
            return True

        page = read.page
        if read.replace_tail:
            assert page is not None
            self._ack_page = None
            self._channel_ack_pages.clear()
            await self.contents.remove_children(widget for _, widget in self._history)
            self._history.clear()
            self._has_older = page.has_older
            self._has_newer = False
            await self._mount_page(page, older=False)
            self._display_identity = display_identity(HistoryKind(self.kind), page)
            self._poll_cursor = (page.newest_seq if page.has_newer else high_water) or high_water
            return True
        if high_water <= self._poll_cursor:
            return follow
        if page is None:
            return follow
        self._display_identity = display_identity(HistoryKind(self.kind), page)
        follow = not self._has_newer and self.window.follows_tail
        if page.messages and follow:
            await self._mount_page(page, older=False)
            self._poll_cursor = (
                page.newest_seq if page.has_newer else high_water
            ) or high_water
        else:
            if page.messages:
                self._has_newer = True
            self._poll_cursor = high_water
        return follow

    def _mark_visible_after_layout(self) -> None:
        if self._ack_inflight or not self.is_attached:
            return
        from toad.comms_root import root_is_current

        if self._wire is None or not root_is_current(self._wire.root):
            self.display = False
            return
        painted = set(self._painted_message_sequences())
        original_page = None
        if self.kind == "dm":
            page = self._ack_page
            if page is None or page.newest_seq not in painted:
                return
            basis = page.display_basis
            if basis is None or basis.older_unread:
                return
            inbound = (
                message.seq for message in page.messages
                if message.sender in basis.peer_names and message.target in basis.viewer_names
            )
            if any(sequence not in painted for sequence in inbound):
                return
            original_page = page
            page = replace(
                page,
                messages=tuple(message for message in page.messages if message.seq in painted),
                display_basis=replace(basis, displayed=basis.displayed.select(painted)),
            )
        else:
            mounted = {message.seq for message, _ in self._history}
            self._channel_ack_pages = {
                seq: source for seq, source in self._channel_ack_pages.items() if seq in mounted
            }
            original_page = next(
                (source for seq, source in self._channel_ack_pages.items() if seq in painted), None
            )
            if original_page is None:
                return
            page = original_page
            scope = page.display_scope
            if scope is None or scope.displayed is None:
                return
            selected = {
                seq for seq, source in self._channel_ack_pages.items()
                if source is page and seq in painted
            }
            # Subset the captured proof, never a reconstructed watermark. Keep
            # unpainted rows pending so scrolling can acknowledge them later.
            page = replace(
                page, messages=tuple(message for message in page.messages if message.seq in selected),
                display_scope=replace(scope, displayed=scope.displayed.select(selected)),
            )
        self._ack_inflight = True
        self.run_worker(self._mark_painted_page(page, original_page), group="comms-painted-read")

    async def _mark_painted_page(self, page: MessagePage, original_page: MessagePage | None = None) -> None:
        try:
            comms = self._wire
            from toad.comms_root import implicit_root, root_is_current, run_selected_write

            if comms is None or not self.is_attached or not self.screen.is_active:
                return
            if not root_is_current(comms.root):
                self.display = False
                return
            project = str(self.project_path)
            target = self.target
            if self.kind == "dm":
                assert page.display_basis is not None and page.newest_seq is not None
                await asyncio.to_thread(
                    run_selected_write, comms.root, comms.mark_dm_view_read, target,
                    worktree=project, through=page.newest_seq,
                    expected_display_basis=page.display_basis, implicit=implicit_root(),
                )
            else:
                assert page.display_scope is not None and page.newest_seq is not None
                await asyncio.to_thread(
                    run_selected_write, comms.root, comms.mark_channel_view_read, target,
                    worktree=project, through=page.newest_seq,
                    expected_scope=page.display_scope, implicit=implicit_root(),
                )
            if self._ack_page is page or self._ack_page is original_page:
                self._ack_page = None
            if original_page is not None:
                for message in page.messages:
                    if self._channel_ack_pages.get(message.seq) is original_page:
                        del self._channel_ack_pages[message.seq]
        except ValueError:
            # The peer, viewer, channel scope, or bus changed after page
            # fetch. Discard mounted history and fetch the current projection.
            if self.is_attached:
                async with self._refresh_lock:
                    await self.contents.remove_children(widget for _, widget in self._history)
                    self._history.clear()
                    self._history_initialized = False
                    self._poll_cursor = 0
                    self._revision = None
                    self._display_identity = None
                    self._has_older = False
                    self._has_newer = False
            self._ack_page = None
            self._channel_ack_pages.clear()
        finally:
            self._ack_inflight = False
            if self.is_attached:
                self.call_after_refresh(self._mark_visible_after_layout)

    async def _refresh(self) -> None:
        if not self.is_attached or self._wire is None:
            return
        from toad.comms_root import root_is_current

        if not root_is_current(self._wire.root):
            self.display = False
            return
        try:
            if self.screen is not self.app.screen:
                self._warm_history()
                return
        except Exception:
            return
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            try:
                comms = self._wire
                show_loading = (not self._history_initialized or
                                self._history_warm_task is not None and not self._history_warm_task.done())
                if show_loading:
                    self.throbber.busy = True
                try:
                    read = await self._read_history()
                finally:
                    if show_loading and self.is_attached:
                        self.throbber.busy = False
                if not self.is_attached or read.request != self._history_request():
                    return
                if not root_is_current(comms.root):
                    self.display = False
                    return
                if self.screen is not self.app.screen:
                    self._prepared_history = read
                    return
                revision = read.revision
                if revision == self._revision:
                    self.call_after_refresh(self._mark_visible_after_layout)
                    if self._edge_check_on_resume:
                        self.call_after_refresh(self._on_window_scroll)
                    return
                # Show the bounded tail before computing roster/sort metadata,
                # which can scan a much larger coordination history.
                follow = await self._refresh_history(read)
                if self.kind != "dm":
                    snapshot = await asyncio.to_thread(comms.coordination_snapshot)
                    self.query_one(ChannelParticipants).update_participants(
                        snapshot.participants(self.target)
                    )
                    self.query_one(ChannelPrompt).set_mention_candidates(
                        snapshot.mention_candidates(self.target)
                    )
                if not self.is_attached or not self.screen.is_active:
                    return
                if not root_is_current(comms.root):
                    self.display = False
                    return
                self.call_after_refresh(self._mark_visible_after_layout)
            except Exception as error:
                message = f"Wire error: {error}"
                if message != self.status:
                    self.flash(message, style="error")
                self.status = message
                return

            self._revision = revision

            target = self.target
            info = await asyncio.to_thread(comms.agent_info_of, target) if self.kind == "dm" else None
            if not self.is_attached or self.target != target:
                return
            if self._unknown_send is not None:
                root_id, sequence, message_id = self._unknown_send
                self.status = (
                    f"Send UNKNOWN {root_id}/{sequence}/{message_id}; "
                    "inspect the bus, do not retry"
                )
            elif self._human_admission_blocked:
                self.status = self._send_block_reason
            elif info is not None:
                self.status = " · ".join(
                    value
                    for value in (info.model or "", info.context_label)
                    if value
                )
            else:
                self.status = ""
            if follow and self.window.follows_tail:
                self.window.anchor()
        if self._has_newer or (self._has_older and self.window.max_scroll_y == 0):
            self.call_after_refresh(self._on_window_scroll)

    async def submit_input(self, event: messages.UserInputSubmitted) -> None:
        if not event.body.strip():
            return
        if self._unknown_send is not None or self._human_admission_blocked:
            self.flash("Send pending/UNKNOWN/blocked; inspect, do not retry", style="error")
            return
        try:
            from toad.comms_root import implicit_root, root_is_current, run_selected_write

            if self._wire is None or not root_is_current(self._wire.root):
                raise ValueError("Comms route changed; reopen this view before sending")
            comms = self._wire
            # Disable compose through both the worker and the subsequent
            # receipt paint. Cancellation after a committed receipt must not
            # leave an apparently fresh, send-ready draft.
            self._human_admission_blocked = True
            self._send_block_reason = "Send pending; do not retry"
            self.prompt.text = event.body
            self.prompt.prompt_text_area.disabled = True
            send_task = asyncio.create_task(
                asyncio.to_thread(
                    run_selected_write, comms.root, comms.send_user_message,
                    "#all" if self.kind == "irc" else self.target, event.body,
                    worktree=str(self.project_path), implicit=implicit_root(),
                )
            )
            try:
                receipt = await asyncio.shield(send_task)
            except asyncio.CancelledError:
                # Cancelling the UI coroutine does not cancel the worker. The
                # append may already have happened; never present this text as
                # send-ready or launch a second attempt on a different root.
                self._human_admission_blocked = True
                self.prompt.text = event.body
                self.prompt.prompt_text_area.disabled = True
                self._send_block_reason = (
                    "Send cancelled while worker may still write; "
                    "outcome UNKNOWN, inspect the bus, do not retry"
                )
                self.status = self._send_block_reason
                self.prompt.prompt_text_area.tooltip = self.status
                self.flash(self.status, style="error")
                send_task.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )
                return
        except Exception as error:
            from agent_comms import declarations as core_declarations

            unknown_type = getattr(core_declarations, "HumanInitialUnknownError", None)
            if unknown_type is not None and isinstance(error, unknown_type):
                self._unknown_send = (error.wire_root_id, error.wire_seq, error.message_id)
                # Preserve the user's text for inspection, but never put an
                # uncertain send back into an actionable compose control.
                self.prompt.text = event.body
                self.prompt.prompt_text_area.disabled = True
                self.status = f"Send UNKNOWN: {error}; do not retry"
                self.prompt.prompt_text_area.tooltip = self.status
                self.flash(self.status, style="error")
                return
            violation_type = getattr(core_declarations, "RelationViolationError", None)
            if (
                violation_type is not None
                and isinstance(error, violation_type)
                and "UNKNOWN outcome" in str(error)
                and "human send blocked" in str(error)
            ):
                # Core's fail-closed reservation/sequence-gap admission is
                # non-actionable until manual reconciliation, not a fresh
                # pre-append rejection that can safely be resubmitted.
                self._human_admission_blocked = True
                self.prompt.text = event.body
                self.prompt.prompt_text_area.disabled = True
                self._send_block_reason = f"Private human admission blocked: {error}"
                self.status = self._send_block_reason
                self.prompt.prompt_text_area.tooltip = self.status
                self.flash(self.status, style="error")
                return
            self._human_admission_blocked = False
            self._send_block_reason = ""
            self.prompt.text = event.body
            self.prompt.prompt_text_area.disabled = False
            self.flash(f"Send failed: {error}", style="error")
            return
        self._send_block_reason = (
            f"Send receipt {comms.root}/{receipt.seq}/{receipt.message_id}; "
            "awaiting paint, do not retry"
        )
        self.status = self._send_block_reason
        self.prompt.prompt_text_area.tooltip = self.status
        try:
            await self._paint_sent_receipt(comms, receipt, event.body, root_is_current)
        except (asyncio.CancelledError, Exception) as error:
            reason = (
                "interrupted" if isinstance(error, asyncio.CancelledError) else "failed"
            )
            self._send_block_reason = (
                f"Committed send {comms.root}/{receipt.seq}/{receipt.message_id}; "
                f"paint {reason}, inspect before composing"
            )
            self.status = self._send_block_reason
            self.prompt.prompt_text_area.tooltip = self.status
            return
        if root_is_current(comms.root) and any(
            message.message_id == receipt.message_id and message.seq == receipt.seq
            for message, _ in self._history
        ):
            self._human_admission_blocked = False
            self._send_block_reason = ""
            self.prompt.text = ""
            self.prompt.prompt_text_area.disabled = False
            self.prompt.prompt_text_area.tooltip = None
            self.status = ""

    async def _paint_sent_receipt(
        self, comms: Comms, receipt: WireMessage, body: str,
        root_is_current: Callable[[str | Path], bool],
    ) -> None:
        if not root_is_current(comms.root):
            # The send may already have reached the former wire. Do not
            # duplicate it on the successor or paint it under the new route.
            self.display = False
            self.flash(
                "Comms route changed during send; outcome may be uncertain",
                style="error",
            )
            return
        self.prompt_history.current = None
        self.run_worker(self.prompt_history.append(body), group="history")
        self.prompt_history_index = 0
        async with self._refresh_lock:
            if self._has_newer:
                await self.contents.remove_children(widget for _, widget in self._history)
                self._history.clear()
                self._history_initialized = False
            await self._mount_page(
                MessagePage((receipt,), self._has_older, False), older=False
            )
            self.window.anchor()
        self._revision = None
        await self._refresh()
