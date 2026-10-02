"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations
from functools import partial
from toad.delivery_failure_view import DeliveryFailureView
from toad.mounted_message_history import MountedMessageHistory
from agent_comms.thread_identity import ThreadRole
from toad.widgets.irc_message import MembershipNotice

import asyncio
import re
from collections.abc import Callable
from pathlib import Path

from agent_comms.comms import Comms
from toad.message_viewport import NotificationViewport
from toad.constants import COMMS_REFRESH_INTERVAL
from agent_comms.messages import Message as WireMessage
from agent_comms.comms import wire
from textual import containers, work
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static
from textual.widget import Widget

from toad.conversation_kind import ConversationKind
from toad import messages
from toad.widgets.conversation import (
    Contents,
    ContentsGrid,
    Conversation,
    CursorContainer,
    Window,
)
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.widgets.message_notifications import MessageNotifications
from toad.owner_preparation import read_thread_presentation
from toad.screens.session_view import SessionView


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


from toad.block_navigation import ConversationBlock


class HistoryLoading(ConversationBlock, Static):
    """Channel history loading is an atomic conversation block."""


class ChannelActivityTray(ConversationBlock, containers.VerticalGroup):
    """Channel activity has one declared navigation boundary."""


class CommsChatView(DeliveryFailureView, Conversation):
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
        self.conversation_kind = ConversationKind.decode(kind)
        self._me = me
        self._unknown_send: tuple[str, int, str] | None = None
        self._human_admission_blocked = False
        self._send_block_reason = ""
        self._bound_root = Path(wire_root).resolve() if wire_root is not None else None
        self.input_histories.bind_scope(f"comms:{kind}:{target}")
        self.message_history = MountedMessageHistory(self)
        self._notification_task: asyncio.Task[None] | None = None

    @property
    def kind(self) -> str:
        return self.conversation_kind.declared_name

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                yield CursorContainer(id="cursor-container")
                with Contents(id="contents"):
                    yield HistoryLoading("Loading messages…", id="history-loading")
                    yield ChannelActivityTray(id="comms-activity")
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield self.conversation_kind.activity_widget(self)
            yield self.make_throbber()
            yield self.conversation_kind.prompt(self.target).data_bind(
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
        self.message_history.service = (self.app.coordination_access.service if root == self.app.coordination_access.service.root
                      else wire(root))
        self.agent_info = Content(self._target_label())
        self.agent_ready = True
        self.prepare_prompt()
        self.window.anchor()
        self.watch(self.window, "scroll_y", self.message_history.on_scroll, init=False)
        self.set_interval(COMMS_REFRESH_INTERVAL, self._refresh)
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
        self.update_slash_commands()
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
        return self.conversation_kind.label(self.target)






    def message_block(self, message: WireMessage) -> Widget:
        """The view owns display direction and the membership-notice widget."""
        if message.membership is not None:
            return MembershipNotice(message)
        direction = ("User" if message.sender_role is ThreadRole.USER else
                     "Outbound" if message.sender == self._me else "Inbound")
        return self.message_history.style.block(message, direction=direction)

    async def on_unmount(self) -> None:
        self.message_history.retire()









    def _refresh_notifications(self) -> None:
        """One bounded batch for the painted window; independent of bus revision."""
        if (not self.is_attached or self.message_history.service is None
                or not self.display
                or self._notification_task is not None and not self._notification_task.done()):
            return
        rows = self._visible_notification_rows()
        if rows:
            self._notification_task = asyncio.create_task(self._read_notifications(rows))

    def _visible_notification_rows(self) -> tuple[tuple[WireMessage, Widget], ...]:
        return self.message_history.viewport(NotificationViewport).visible_rows()

    async def _read_thread_activity(self):
        from toad.comms_root import root_is_current

        comms, target = self.message_history.service, self.target
        if comms is None:
            return None
        if not root_is_current(comms.root):
            raise ValueError("Comms route changed")
        presentation = await asyncio.to_thread(read_thread_presentation, comms, target)
        if comms is not self.message_history.service or target != self.target or not root_is_current(comms.root):
            raise ValueError("Comms route changed")
        return presentation

    async def _read_notifications(self, rows: tuple[tuple[WireMessage, Widget], ...]) -> None:
        from toad.comms_root import root_is_current

        comms, target = self.message_history.service, self.target
        if comms is None or not root_is_current(comms.root):
            return
        error = None
        try:
            results = await asyncio.to_thread(
                comms.views.message_notifications, tuple(message for message, _ in rows),
            )
        except Exception as failure:
            error, results = failure, {}
        if (not self.is_attached or self.message_history.service is not comms or self.target != target
                or not self.query_ancestor(SessionView).is_current
                or not root_is_current(comms.root)):
            return
        visible = {widget for _, widget in self._visible_notification_rows()}
        for message, widget in rows:
            if widget in visible:
                feedback = next(iter(widget.query(MessageNotifications)), None)
                if feedback is None:
                    continue  # Style replacement has unmounted this row's children.
                if error is not None:
                    feedback.show_error(error)
                else:
                    feedback.show_result(results.get((message.seq, message.message_id), ()))

    async def _refresh(self) -> None:
        if not self.is_attached or self.message_history.service is None:
            return
        if not self.query_ancestor(SessionView).is_current:
            return
        from toad.comms_root import root_is_current

        if not root_is_current(self.message_history.service.root):
            self.display = False
            return
        self._refresh_notifications()
        if self.message_history.lock.locked():
            return
        async with self.message_history.lock:
            try:
                comms = self.message_history.service
                catalog = await asyncio.to_thread(comms.channels.catalog.read)
                if not self.is_attached or not self.query_ancestor(SessionView).is_current:
                    return
                read_only = self.conversation_kind.read_only(catalog, self.target)
                if read_only:
                    self.prompt.prompt_text_area.disabled = True
                    self.prompt.prompt_text_area.tooltip = "Saved view: read-only history; open an exact channel to send"
                    self.status = "Read-only saved view"
                show_loading = not self.message_history.initialized
                if show_loading:
                    self.on_work_started()
                try:
                    read = await self.app.channel_history_reader.read(self.message_history.request())
                finally:
                    if show_loading:
                        self.on_work_finished()
                if not self.is_attached or not self.query_ancestor(SessionView).is_current:
                    return
                if read.request != self.message_history.request():
                    return
                if not root_is_current(comms.root):
                    self.display = False
                    return
                self.update_slash_commands()
                revision = read.revision
                if revision == self.message_history.revision:
                    self.call_after_refresh(self.message_history.mark_visible)
                    if self.message_history.edge_on_resume:
                        self.call_after_refresh(self.message_history.on_scroll)
                    return
                # Show the bounded tail before computing roster/sort metadata,
                # which can scan a much larger coordination history.
                follow = await self.message_history.publish(read)
                await self.conversation_kind.update_roster(self, comms)
                if not self.is_attached or not self.query_ancestor(SessionView).is_current:
                    return
                if not root_is_current(comms.root):
                    self.display = False
                    return
                self.call_after_refresh(self.message_history.mark_visible)
            except Exception as error:
                message = f"Wire error: {error}"
                if message != self.status:
                    self.flash(message, style="error")
                self.status = message
                return

            self.message_history.revision = revision

            target = self.target
            info = await self.conversation_kind.agent_info(comms, target)
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
                self.status = "Read-only saved view" if read_only else ""
            if follow and self.window.follows_tail:
                self.window.anchor()
        if self.message_history.has_newer or (self.message_history.has_older and self.window.max_scroll_y == 0):
            self.call_after_refresh(self.message_history.on_scroll)

    def command_target_context(self):
        from toad.target_commands import TargetContext
        if self.message_history.service is None:
            return None
        return TargetContext.decode(self.kind)(self.app, self.message_history.service, self.target, self._me, self.project_path,
                             self.app.selected_mode)

    async def submit_input(self, event: messages.UserInputSubmitted) -> None:
        if event.body.strip().startswith("/") and await self.command_catalog.execute(event.body.strip(), self):
            return
        if not event.body.strip():
            return
        if self._unknown_send is not None or self._human_admission_blocked:
            self.flash("Send pending/UNKNOWN/blocked; inspect, do not retry", style="error")
            return
        try:
            from toad.comms_root import implicit_root, root_is_current, run_selected_write

            if self.message_history.service is None or not root_is_current(self.message_history.service.root):
                raise ValueError("Comms route changed; reopen this view before sending")
            comms = self.message_history.service
            catalog = await asyncio.to_thread(comms.channels.catalog.read)
            if self.conversation_kind.read_only(catalog, self.target):
                self.prompt.text = event.body
                self.prompt.prompt_text_area.disabled = True
                self.status = "Read-only saved view; open an exact channel to send"
                self.flash(self.status, style="error")
                return
            # Disable compose through both the worker and the subsequent
            # receipt paint. Cancellation after a committed receipt must not
            # leave an apparently fresh, send-ready draft.
            self._human_admission_blocked = True
            self._send_block_reason = "Send pending; do not retry"
            self.prompt.text = event.body
            self.prompt.prompt_text_area.disabled = True
            send_task = asyncio.create_task(
                asyncio.to_thread(
                    run_selected_write, comms.root, comms.messaging.send_user_message,
                    self.conversation_kind.send_target(self.target), event.body,
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
            from agent_comms.delivery_failure import delivery_failure

            delivery_failure(error).present(self, event.body)
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
            for message, _ in self.message_history.rows
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
        self.run_worker(partial(self.input_histories.prompt.record, body), group="history")
        await self.message_history.paint_receipt(receipt)
        await self._refresh()
