"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations
from toad.core import input_events
from functools import partial
from toad.widgets.wire_history import WireHistory
from toad.message_rows import IrcMessageStyle
from toad.wire_history import WireSource

import asyncio
import re
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.field_codec import FieldCodec
from agent_comms.mro_dispatch import handles
from toad.core import events as core_events
from toad.core.source_events import TranscriptSourceWorkFinished
from agent_comms.messages import Message as WireMessage
from textual import containers, work
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static
from textual.worker import Worker

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
from toad.widgets.transcript_history import JumpToLatest
from toad.screens.session_view import SessionView
from toad.command_catalog import CommandCatalog


def _comms_root() -> Path:
    from agent_comms.route_selection import current_root

    return current_root()


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-")
        or "session"
    )


def resolve_session_thread(
    comms, project_path: Path, preferred: str | None = None, *, source_root: str | None = None,
) -> str | None:
    """Resolve an exact bound thread or an unbound project's registry identity."""
    if source_root is not None:
        if Path(source_root).expanduser().resolve() != comms.root.resolve():
            raise ValueError("Comms route changed; this session retains its former wire")
        return comms.registry.require(preferred).name
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


class CommsChatView(Conversation):
    """A wire-backed conversation using Toad's normal transcript primitives."""

    BINDINGS = Conversation.BINDINGS[:5]

    def __init__(
        self,
        project_path: Path,
        *,
        target: str,
        kind: type[ConversationKind],
        me: str,
        wire_root: str | None = None,
    ) -> None:
        super().__init__(project_path)
        self.target = target
        self.conversation_kind = kind
        self._me = me
        # The observer's announcement the last refresh began from.
        self._refreshed_from = None
        self._bound_root = Path(wire_root).resolve() if wire_root is not None else None
        self.input_histories.bind_scope(f"comms:{FieldCodec.encode(kind)}:{target}")
        self.message_history = WireHistory(self)

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                yield CursorContainer(id="cursor-container")
                with Contents(id="contents"):
                    yield HistoryLoading("Loading messages…", id="history-loading")
                    yield self.message_history
                    yield ChannelActivityTray(id="comms-activity")
            yield containers.Center(
                JumpToLatest("↓ Back to bottom · Esc", id="back-to-bottom"),
                id="back-to-bottom-bar",
            )
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield self.conversation_kind.activity_widget(self)
            yield self.make_throbber()
            yield self.conversation_kind.prompt(self.target).data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent=Conversation.agent,
                status=Conversation.status,
            )

    async def initialize_view(self) -> None:
        # Reuse the canonical core service already shared by tab sidebars and
        # transcript readers. Its revision-aware caches remain model-owned.
        try:
            root = await self.app.preparation.run_thread(_comms_root)
        except (OSError, ValueError, RuntimeError):
            self.display = False
            return
        if self._bound_root is not None and root != self._bound_root:
            self.display = False
            return
        shared = await self.app.preparation.run_thread(
            lambda: self.app.coordination_access.service)
        if shared.root != root:
            self.display = False
            return
        comms = shared
        self.message_history.open(WireSource(
            comms, self.conversation_kind, self.target, Path(self.project_path), self._me,
            IrcMessageStyle(),
        ))
        self.agent_info = Content(self._target_label())
        self.agent_ready = True
        self.refresh_thread_status()
        self.prepare_prompt()
        self.window.anchor()
        # CommsScreen has already presented its route before mounting this
        # view. Start its asynchronous page read now, overlapping it with the
        # remaining control mounts rather than waiting for another empty
        # history frame. The history runs the read as its own source work.
        await self._refresh()

    @handles(core_events.CoordinationObserved)
    async def _command_source_changed(self, event) -> None:
        """One canonical observation invalidates commands and the mounted source."""
        await super()._command_source_changed(event)
        await self._refresh()

    @handles(core_events.SessionSelected)
    async def _selected_source_changed(self, event) -> None:
        """A retained view reads current source after its original tab admission."""
        await super()._selected_commands_changed(event)
        await self._refresh()

    @handles(TranscriptSourceWorkFinished)
    async def on_transcript_source_work_finished(self, event) -> None:
        """Reconcile an observation which arrived during this source's work."""
        super().on_transcript_source_work_finished(event)
        history = self.message_history
        source = history.source
        access = self.app.coordination_access
        if event.publisher is not history or source is None:
            return
        self.settle_user_message()
        if (not history.state.accepts_source_work
                or history.undrawn
                or source.comms is not access.observed_service
                or access.revision is None):
            return
        if self._refreshed_from != access.revision:
            # The observer announced a change while this work ran. The history
            # may have read it from the stores already; the participants line
            # reads the observer's sidebar, which only now shows it.
            await self._refresh()
            return
        if history.revision == access.revision:
            return
        snapshot = history.source_snapshot()
        if not snapshot.current(history):
            return
        # A read can also be newer than the observer's last announcement. Their
        # file revisions are identities, not an ordering: ask the service
        # itself before reading again, rather than rereading an already
        # current page until the observer's next tick.
        try:
            revision = await self.app.preparation.run_thread(source.comms.views.revision)
        except (OSError, ValueError, RuntimeError):
            # An unavailable or replaced route has no revision to read. Its
            # observer remains responsible for the next observation.
            return
        if (source is history.source and snapshot.current(history)
                and source.comms is access.observed_service
                and history.revision != revision):
            await self._refresh()

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
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.events)
        self.update_slash_commands()
        prompt.agent_info = self.agent_info
        prompt.sync_session()
        prompt.shell_mode = False
        prompt.update_prompt()
        from toad.screens.session_view import SessionView

        if self.query_ancestor(SessionView).is_current:
            prompt.focus()

    def watch_agent(self, agent) -> None:
        """Keep the inherited agent reactive from turning this into a shell session."""
        self.agent_info = Content(self._target_label())

    @work
    async def watch_agent_ready(self, ready: bool) -> None:
        """Comms readiness has no shell process to await."""

    def _target_label(self) -> str:
        return self.conversation_kind.label(self.target)

    def transcript_scope(self) -> None:
        """DM/channel history belongs to WireHistory, not a native transcript."""
        return None

    def status_thread(self) -> tuple[str, str] | None:
        """Peer status does not grant access to the peer's full transcript."""
        name = self.conversation_kind.historical_thread(self.target)
        source = self.message_history.source
        return (str(source.comms.root), name) if name is not None and source is not None else None

    async def _refresh(self) -> Worker | None:
        history = self.message_history
        if not self.is_attached or history.source is None:
            return
        if not self.query_ancestor(SessionView).is_current:
            return
        history.check_notifications()
        return history.schedule_source_work(self._refresh_source)

    async def _refresh_source(self) -> None:
        """Read what changed in the conversation and draw it: the history's source work."""
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

        try:
            history = self.message_history
            announced = self.app.coordination_access.revision
            newly_announced = announced != self._refreshed_from
            self._refreshed_from = announced
            snapshot = history.source_snapshot()
            if not await history.source_is_current(snapshot):
                if snapshot.current(history):
                    self.display = False
                return
            source = history.source
            comms = source.comms
            catalog = await asyncio.to_thread(comms.channels.catalog.read)
            if not await history.source_is_current(snapshot):
                return
            read_only = self.conversation_kind.read_only(catalog, self.target)
            if read_only:
                self.prompt.prompt_text_area.disabled = True
                self.prompt.prompt_text_area.tooltip = "Saved view: read-only history; open an exact channel to send"
                self.status = "Read-only saved view"
            undrawn = history.undrawn
            if undrawn:
                self.on_work_started()
            try:
                changed = await history.read_changes()
            finally:
                if undrawn:
                    self.on_work_finished()
            # A sent message may now be drawn: composing resumes before the roster is read.
            self.settle_user_message()
            if changed and undrawn and (placeholder := self.query_one_optional("#history-loading")):
                placeholder.remove()
        except (CoordinationReadUnavailable, StaleRevision):
            raise
        except (OSError, ValueError, RuntimeError) as error:
            self._show_wire_error(error)
            return
        # The participants line and the status line read the observer's sidebar
        # and the agent records, which can take seconds on a busy bus. They are
        # not this conversation's messages, so they run after this work ends
        # and the history can load pages while they wait.
        self.run_worker(partial(self._refresh_labels, comms, changed, newly_announced, read_only),
                        group=self.LABELS_GROUP)

    LABELS_GROUP = "chat-labels"

    def _show_wire_error(self, error: Exception) -> None:
        message = f"Wire error: {error}"
        if message != self.status:
            self.flash(message, style="error")
        self.status = message

    async def _refresh_labels(self, comms, changed: bool, newly_announced: bool, read_only: bool) -> None:
        """Show who is in the conversation and its status line, for the history as it is drawn now."""
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

        history = self.message_history
        snapshot = history.source_snapshot()
        source, target = history.source, self.target
        try:
            # An unchanged history may have read the stores before the observer
            # announced the change; the participants line reads the observer's sidebar.
            if changed or newly_announced:
                await self.conversation_kind.update_roster(self, comms)
            if changed:
                if not await history.source_is_current(snapshot):
                    if snapshot.current(history):
                        self.display = False
                    return
                if (not self.is_attached or source is not history.source
                        or not self.query_ancestor(SessionView).is_current):
                    return
            self.call_after_refresh(history.mark_visible)
            if not changed:
                return
            info = await self.conversation_kind.agent_info(comms, target)
        except (CoordinationReadUnavailable, StaleRevision):
            # The coordination store is busy or moved on: the observer's next
            # announcement refreshes this view and reads the labels again.
            return
        except (OSError, ValueError, RuntimeError) as error:
            self._show_wire_error(error)
            return
        if not await history.source_is_current(snapshot) or self.target != target:
            return
        if self._unknown_send is not None:
            root_id, sequence, message_id = self._unknown_send
            self.status = (
                f"Send UNKNOWN {root_id}/{sequence}/{message_id}; "
                "inspect the bus, do not retry"
            )
        elif self._send_block_reason:
            self.status = self._send_block_reason
        elif info is not None:
            self.status = " · ".join(
                value
                for value in (
                    info.model or "",
                    info.context_usage.label if info.context_usage is not None else "",
                )
                if value
            )
        else:
            self.status = "Read-only saved view" if read_only else ""
        if self.window.follows_tail:
            self.window.anchor()
        if history.has_newer or (history.has_older and self.window.max_scroll_y == 0):
            history.request_preparation()

    async def command_target_context(self):
        from toad.target_commands import TargetContext
        if self.message_history.source is None:
            return None
        return TargetContext(self.app, self.message_history.source.comms, self.target, self._me, self.project_path,
                             self.query_ancestor(SessionView).id)

    async def submit_input(self, event: input_events.UserInputSubmitted) -> None:
        if event.body.strip().startswith("/") and await CommandCatalog.execute(event.body.strip(), self):
            return
        if not event.body.strip():
            return
        history = self.message_history
        source, target = history.source, self.target
        if source is None:
            self.delivery_refused("Conversation source is not ready", event.body)
            return
        comms = source.comms
        try:
            catalog = await asyncio.to_thread(comms.channels.catalog.read)
        except (OSError, ValueError, RuntimeError) as error:
            self.delivery_refused(str(error), event.body)
            return
        if self.conversation_kind.read_only(catalog, target):
            self.prompt.text = event.body
            self.prompt.prompt_text_area.disabled = True
            self.status = "Read-only saved view; open an exact channel to send"
            self.flash(self.status, style="error")
            return

        def current() -> bool:
            return self.is_attached and source is history.source and target == self.target

        await self.deliver_user_message(
            comms.root, self.conversation_kind.send_target(target), event.body, current,
            partial(self._show_sent, body=event.body),
        )

    async def _show_sent(self, sent: WireMessage, body: str) -> None:
        """Follow the conversation's end and read it now; composing resumes once `sent` is drawn."""
        self.run_worker(partial(self.input_histories.prompt.record, body), group="history")
        self.window.jump_to_latest()
        await self._refresh()
        self.settle_user_message()

    def draws_user_message(self, sent) -> bool:
        return self.message_history.draws(sent)
