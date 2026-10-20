"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations
from toad.widgets.presentation_window import OLDER_END, NEWER_END
from toad.core import input_events
from functools import partial
from toad.widgets.wire_history import WireHistory
from toad.message_rows import IrcMessageStyle
from toad.wire_history import WireSource
from toad.transcript_publication import NoView, ViewBinding

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
from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.flash import Flash
from toad.widgets.prompt import Prompt
from toad.screens.session_view import SessionView
from toad.command_catalog import CommandCatalog


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-")
        or "session"
    )


from toad.block_navigation import ConversationBlock


class HistoryLoading(ConversationBlock, Static):
    """Channel history loading is an atomic conversation block."""


class CommsChatView(Conversation):
    """A wire-backed conversation using Toad's normal transcript primitives."""

    BINDINGS = Conversation.BINDINGS[:5]

    def __init__(
        self,
        project_path: Path,
        *,
        conversation: ConversationKind,
        me: str,
        wire_root: str | None = None,
        transcript=None,
    ) -> None:
        super().__init__(project_path, transcript=transcript)
        self.conversation = conversation
        self._me = me
        # The observer's announcement the last refresh began from.
        self._refreshed_from = None
        self._bound_root = Path(wire_root).resolve() if wire_root is not None else None
        self.input_histories.bind_scope(f"comms:{FieldCodec.encode(type(conversation))}:{conversation.target}")
        self.message_contents = Contents(id="contents")
        self.message_history = WireHistory.empty(view=self, notification_view=self.message_contents)

    def transcript_binding(self) -> ViewBinding:
        """A wire conversation has no native transcript to publish."""
        return NoView()

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                yield CursorContainer(id="cursor-container")
                with self.message_contents:
                    yield HistoryLoading("Loading messages…", id="history-loading")
                    yield self.message_history
        yield Flash()
        with containers.Vertical(id="prompt-stack"):
            yield from self.conversation.compose_activity(self)
            yield self.throbber
            yield self.conversation.prompt().data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent_binding=Conversation.agent_binding,
                status=Conversation.status,
            )

    async def initialize_view(self) -> None:
        # Reuse the canonical core service already shared by tab sidebars and
        # transcript readers. Its revision-aware caches remain model-owned.
        shared = await self.app.preparation.run_thread(
            lambda: self.app.coordination_access.observation.observed().service)
        if self._bound_root is not None and self._bound_root != shared.root:
            raise ValueError(
                f"Conversation root {self._bound_root} differs from observed root {shared.root}"
            )
        comms = shared
        self.message_history.open(WireSource(
            comms, self.conversation, Path(self.project_path), self._me,
            IrcMessageStyle(),
        ))
        self.agent_info = Content(self.conversation.label())
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
        """A retained view reads current source after its tab opens."""
        await super()._selected_commands_changed(event)
        await self._refresh()

    @handles(TranscriptSourceWorkFinished)
    async def on_transcript_source_work_finished(self, event) -> None:
        """Reconcile an observation which arrived during this source's work."""
        super().on_transcript_source_work_finished(event)
        history = self.message_history
        source = history.page_source
        access = self.app.coordination_access
        if event.publisher is not history:
            return
        self.settle_user_message()
        if (not history.state.accepts_source_work
                or not source.uses_observation(access.observation.observed())):
            return
        if self._refreshed_from != access.revision:
            # The observer announced a change while this work ran. The history
            # may have read it from the stores already; mention completion
            # reads the observer's snapshot, which only now shows it.
            await self._refresh()
            return
        if history.revision.stores == access.revision:
            return
        snapshot = history.source_snapshot()
        if not snapshot.current(history):
            return
        # A read can also be newer than the observer's last announcement. Their
        # file revisions are identities, not an ordering: ask the service
        # itself before reading again, rather than rereading an already
        # current page until the observer's next tick.
        revision = await source.read_revision()
        if (source is history.page_source and snapshot.current(history)
                and source.uses_observation(access.observation.observed())
                and history.revision.stores != revision):
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

    def watch_agent_binding(self, agent) -> None:
        """Keep the inherited agent reactive from turning this into a shell session."""
        self.agent_info = Content(self.conversation.label())

    def transcript_scope(self) -> None:
        """DM/channel history belongs to WireHistory, not a native transcript."""
        return None

    def status_thread(self) -> StatusThread:
        """Peer status does not grant access to the peer's full transcript."""
        return self.message_history.page_source.status_thread(self.app.coordination_access)

    async def _refresh(self) -> Worker | None:
        history = self.message_history
        if not self.is_attached or not self.query_ancestor(SessionView).is_current:
            return
        return history.page_source.schedule_refresh(self)

    async def _refresh_source(self) -> None:
        """Read what changed in the conversation and draw it: the history's source work."""
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

        try:
            history = self.message_history
            announced = self.app.coordination_access.revision
            newly_announced = announced != self._refreshed_from
            undrawn = history.undrawn
            if undrawn:
                self.on_work_started()
            try:
                changed = await history.read_changes()
            finally:
                if undrawn:
                    self.on_work_finished()
            # Source observation and its pending first page belong to the
            # history, even before this tab is drawable. Composer work follows.
            source = history.page_source
            snapshot = history.source_snapshot()
            if not await history.source_is_current(snapshot):
                return
            read_only = await source.read_only()
            if not await history.source_is_current(snapshot):
                return
            await self.refresh_composer(read_only)
            self._refreshed_from = announced
            # A sent message may now be drawn: composing resumes before mentions are read.
            self.settle_user_message()
        except (CoordinationReadUnavailable, StaleRevision):
            raise
        # Composer mentions and DM status read the observer's snapshot
        # and the agent records, which can take seconds on a busy bus. They are
        # not this conversation's messages, so they run after this work ends
        # and the history can load pages while they wait.
        self.run_worker(partial(self._refresh_labels, source, changed, newly_announced, read_only),
                        group=self.LABELS_GROUP)

    LABELS_GROUP = "chat-labels"

    async def _refresh_labels(self, source, changed: bool, newly_announced: bool, read_only: bool) -> None:
        """Refresh composer mentions and status for the history as it is drawn now."""
        from agent_comms.coordination_errors import CoordinationReadUnavailable, StaleRevision

        history = self.message_history
        snapshot = history.source_snapshot()
        conversation = self.conversation
        if source is not history.page_source:
            return
        try:
            # An unchanged history may have read the stores before the observer
            # announced the change; mention completion reads the observer's snapshot.
            if changed or newly_announced:
                await source.update_mentions(self)
            if changed:
                if not await history.source_is_current(snapshot):
                    return
                if (not self.is_attached or source is not history.page_source
                        or not self.query_ancestor(SessionView).is_current):
                    return
            self.call_after_refresh(history.mark_visible)
            if not changed:
                return
            status = await source.status_text(read_only=read_only)
        except (CoordinationReadUnavailable, StaleRevision):
            # The coordination store is busy or moved on: the observer's next
            # announcement refreshes this view and reads the labels again.
            return
        if not await history.source_is_current(snapshot) or self.conversation != conversation:
            return
        await self.refresh_composer(read_only, status)
        if self.window.follows_tail:
            self.window.anchor()
        if NEWER_END.visible_more(history) or (OLDER_END.visible_more(history) and self.window.max_scroll_y == 0):
            history.request_preparation()

    async def composer_read_only(self) -> bool:
        """Reacquire channel access from this view's current Core source."""
        return await self.message_history.page_source.read_only()

    async def command_target_context(self):
        return self.message_history.page_source.command_context(self)

    async def submit_input(self, event: input_events.UserInputSubmitted) -> None:
        if event.body.strip().startswith("/") and await CommandCatalog.execute(event.body.strip(), self):
            return
        if not event.body.strip():
            return
        await self.message_history.page_source.submit_input(self, event)

    async def _show_sent(self, sent: WireMessage, body: str) -> None:
        """Follow the conversation's end and read it now; composing resumes once `sent` is drawn."""
        self.run_worker(partial(self.input_histories.prompt.record, body), group="history")
        self.window.jump_to_latest()
        await self._refresh()
        self.settle_user_message()

    def draws_user_message(self, sent) -> bool:
        return self.message_history.draws(sent)
