"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations
from agent_comms.messaging.revision_views import RosterView
from agent_comms.presentation import NoRevision, ReadState

import re
from functools import partial
from pathlib import Path

from agent_comms.coordination.errors import CoordinationReadUnavailable, ReadAgain
from agent_comms.messaging.display_references import (
    CurrentDisplayReferences,
    ReferenceContext,
)
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.nominal.field_codec import FieldCodec
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from metaclass_registry.mro_dispatch import handles
from textual.app import ComposeResult
from textual.content import Content

from toad.client.history import WireSource
from toad.client.submission import SubmissionStart
from toad.client.conversation import ConversationKind
from toad.conversation_submission import AgentInputSubmission, ConversationSubmissions
from toad.core import events as core_events
from toad.core.source_events import TranscriptSourceWorkFinished
from toad.core_event_carrier import CoreEventMessage
from toad.client.referenced_core import ReferencedCore
from toad.session_scope import SessionScope
from toad.status_thread import StatusThread
from toad.submission_queue import NoQueueSource, QueueSource
from toad.transcript_publication import ViewBinding
from toad.transcript_scope import NoTranscript
from toad.client.history_state import DEFERRED_WORK, SourceWork
from toad.widgets.channel_activity import ChannelActivity
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.conversation import (
    Contents,
    ContentsGrid,
    Conversation,
    CursorContainer,
    PromptStack,
    Window,
)
from toad.widgets.flash import Flash
from toad.widgets.prompt import MessagePrompt, Prompt
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.wire_history import HistoryLoading, WireFragment, WireHistory
from toad.wire_conversation_view import WireConversationView
from toad.client.pending import HistoryPage


def session_thread_name(project_path) -> str:
    """The wire thread name for a Toad project directory (ACP naming)."""
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "-", Path(project_path).name or "session").strip("-")
        or "session"
    )




class CommsChatView(WireConversationView):
    """A wire-backed conversation using Toad's normal transcript primitives."""

    queue_source: QueueSource = NoQueueSource()

    def __init__(
        self,
        project_path: Checkout,
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
        self.input_histories.bind_scope(f"comms:{FieldCodec.encode(type(conversation))}:{conversation.input_scope}")
        self.message_contents = Contents()
        self.message_history = WireHistory.empty(view=self, notification_view=self.message_contents)

    def transcript_binding(self) -> ViewBinding:
        """A wire conversation has no native transcript to publish."""
        return ViewBinding()

    def compose(self) -> ComposeResult:
        with Window():
            with ContentsGrid():
                yield CursorContainer()
                with self.message_contents:
                    yield HistoryLoading(HistoryPage.label)
                    yield self.message_history
        yield Flash()
        with PromptStack():
            yield self.throbber_above
            yield self.conversation.prompt(self).data_bind(
                project_path=Conversation.project_path,
                working_directory=Conversation.working_directory,
                agent_info=Conversation.agent_info,
                agent_binding=Conversation.agent_binding,
                status=Conversation.status,
            )
            # Under the prompt, not over it: who is here is reference, and reference
            # belongs below the thing you are typing into rather than between you and
            # the conversation you are reading.
            yield from self.conversation.compose_activity(self)

    async def initialize_view(self) -> None:
        # Reuse the canonical core service already shared by tab sidebars and
        # transcript readers. Its revision-aware caches remain model-owned.
        observed = await self.app.preparation.run_thread(
            lambda: self.app.coordination_access.observation.observed())
        if self._bound_root is not None and self._bound_root != observed.root:
            raise ValueError(
                f"Conversation root {self._bound_root} differs from observed root {observed.root}"
            )
        source = WireSource(
            observed.root, self.conversation, self.project_path, self._me,
            self.settings.ui.message_style(), access=self.app.coordination_access, core=observed.core,
            fragments=WireFragment,
        )
        self.queue_source = source
        self.message_history.initialize_source(source)
        # The view hears its history's source work and Core's observations
        # from before its first read, so no completion arrives unheard.
        self.observe_core(self.app.coordination_access.events)
        self.observe_core(self.app.events)
        # The label shows the conversation's initial name until the sidebar's
        # references arrive (ReferenceContext), so identity does not wait for them.
        self.refresh_identity()
        self.window.anchor()
        # CommsScreen has already presented its route before mounting this
        # view. Start its asynchronous page read now, overlapping it with the
        # sidebar observation and the remaining control mounts. The history
        # reads Core directly and runs the read as its own source work.
        # Nothing here waits for the sidebar: the composer's commands load
        # when its references are current (referenced_identity).
        await self._refresh()
        self.prepare_prompt()

    @handles(core_events.CoordinationObserved)
    async def _coordination_observed(self, event: core_events.CoordinationObserved) -> None:
        """One canonical observation invalidates commands and the mounted source."""
        self.prompt.slash_complete.refresh_commands()
        await self._refresh()

    @handles(core_events.SessionSelected)
    async def _selected_source_changed(self, event: core_events.SessionSelected) -> None:
        """A retained view reads current source after its tab opens."""
        self.refresh_identity()
        await self._refresh()

    @handles(core_events.LinkContextChanged)
    async def _command_source_changed(self, event: core_events.LinkContextChanged) -> None:
        """The sidebar's references changed: the label and commands follow them."""
        await super()._command_source_changed(event)
        self.refresh_identity()

    @handles(TranscriptSourceWorkFinished)
    async def on_transcript_source_work_finished(self, event: TranscriptSourceWorkFinished, message: CoreEventMessage) -> None:
        """Reconcile an observation which arrived during this source's work."""
        super().on_transcript_source_work_finished(event, message)
        history = self.message_history
        source = history.page_source
        access = self.app.coordination_access
        if message.publisher is not history:
            return
        self.submissions.settle()
        if (not history.state.accepts_source_work
                or not source.uses_observation(access.observation.observed())):
            return
        if self._refreshed_from != access.revision:
            # The observer announced a change while this work ran. The history
            # may have read it from the stores already; mention completion
            # reads the observer's snapshot, which only now shows it.
            await self._refresh()
            return
        if source.revision.matches_stores(access.revision):
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
                and not source.revision.matches_stores(revision)):
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
        self.refresh_identity()
        prompt.agent_info = self.agent_info
        prompt.sync_session()
        prompt.shell_mode = False
        prompt.update_prompt()
        if self.query_ancestor(SessionScope).is_current:
            prompt.focus()

    def watch_agent_binding(self, agent) -> None:
        """A message composer has no operational agent projection."""

    def refresh_identity(self) -> None:
        """The view's page source dispatches the references of the root it was opened on."""
        self.message_history.page_source.refresh_identity(self)

    @handles(ReferenceContext)
    def preparing_identity(self, references) -> None:
        self.agent_info = Content(self.conversation.initial_label)

    @handles(CurrentDisplayReferences)
    def referenced_identity(self, references) -> object:
        # Composer commands read these references (command_target_context).
        self.agent_info = Content(self.conversation.label(references))
        self.refresh_thread_status()
        self.update_slash_commands()
        return self.DISCARD

    def transcript_scope(self) -> NoTranscript:
        """DM/channel history belongs to WireHistory, not a native transcript."""
        return NoTranscript()

    async def _refresh(self) -> SourceWork:
        history = self.message_history
        if not self.is_attached:
            return DEFERRED_WORK
        return history.page_source.schedule_refresh(self)

    async def _refresh_source(self) -> None:
        """Read what changed in the conversation and draw it: the history's source work.
        Thread-config reads (compose, status, mentions, label) are driven by
        thread_presented, not by every bus message."""
        history = self.message_history
        announced = self.app.coordination_access.revision
        await history.read_changes()
        self._refreshed_from = announced
        self.submissions.settle()
        # Thread config (compose, label, status, mentions) is read on the first refresh and when
        # the roster moved, the roster owner's own signal: channels get no thread_presented.
        if announced.changed_since(RosterView(), self._config_revision):
            self._config_revision = announced
            self.run_worker(self._refresh_thread_config, group=self.LABELS_GROUP)

    _config_revision: ReadState = NoRevision()

    LABELS_GROUP = "chat-labels"

    def thread_presented(self, presentation) -> None:
        super().thread_presented(presentation)
        self.run_worker(self._refresh_thread_config, group=self.LABELS_GROUP)

    async def _refresh_thread_config(self) -> None:
        """Read compose access, status, mentions and label — facts that change when thread
        config changes (ThreadsObserved), not on every bus message."""
        history = self.message_history
        source = history.page_source
        snapshot = history.source_snapshot()
        if not await history.source_is_current(snapshot):
            return
        compose = await source.compose_access()
        if not await history.source_is_current(snapshot):
            return
        await self.refresh_composer(compose)
        try:
            await source.update_mentions(self)
            if not await history.source_is_current(snapshot):
                return
            self.call_after_refresh(history.mark_visible)
            status = await source.status_text(read_only=compose.read_only)
        except (CoordinationReadUnavailable, ReadAgain):
            return
        if not await history.source_is_current(snapshot) or self.conversation != self.conversation:
            return
        self.thread_status = status
        if self.window.follows_tail:
            self.window.anchor()


    def channel_prompt(self, placeholder: str) -> ChannelPrompt:
        return ChannelPrompt(project=self.project_path, placeholder=placeholder, submissions=self.submissions)

    def message_prompt(self) -> MessagePrompt:
        return MessagePrompt(project=self.project_path, submissions=self.submissions)

    def compose_channel_activity(self) -> ComposeResult:
        yield ChannelActivity(self)

    def compose_peer_activity(self, peer: ThreadIncarnation) -> ComposeResult:
        self.thread_activity = ConversationSessionDetails(peer)
        yield self.thread_activity

    async def update_channel_mentions(self, source: ReferencedCore) -> None:
        history = self.message_history
        shown = history.source_snapshot()
        conversation = self.conversation
        access = self.app.coordination_access
        answer = await access.current_sidebar()
        if not access.observation.observes(source.root):
            raise ValueError("Channel mentions belong to another Core root")
        mentions = await self.app.preparation.run_thread(conversation.mention_candidates, answer)
        if not await history.source_is_current(shown) or self.conversation != conversation:
            return
        # Mentions are read in the chat-labels worker, which runs after the drawing work
        # and can take seconds on a busy bus (the chat's refresh worker). The composer can be
        # removed in that window, and a view with no composer has nothing to tell: the
        # query answers membership, so no match is not an exception.
        for prompt in self.query(ChannelPrompt):
            prompt.set_mention_candidates(mentions)

    def queue_controls_changed(self) -> None:
        """A message view has no goal bar to redraw."""

    async def show_sent(self, sent: MessageReference) -> None:
        """Follow the conversation's end and read it now; the queue entry retires once `sent` is drawn."""
        self.window.jump_to_latest()
        await self._refresh()

    def draws_user_message(self, sent) -> bool:
        return self.message_history.draws(sent)
