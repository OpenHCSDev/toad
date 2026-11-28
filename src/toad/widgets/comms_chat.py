"""Native Toad conversation view for an agent-comms channel or DM."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path

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
from toad.client.referenced_core import ReferencedCore
from toad.core.link_context_changed import LinkContextChanged
from toad.session_scope import SessionScope
from toad.status_thread import StatusThread
from toad.submission_queue import NoQueueSource, QueueSource
from toad.transcript_publication import ViewBinding
from toad.transcript_scope import NoTranscript
from toad.widgets.channel_activity import ChannelActivity
from toad.widgets.channel_prompt import ChannelPrompt
from toad.widgets.conversation import (
    ContentsGrid,
    Conversation,
    ConversationContents,
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
        self._bound_root = Path(wire_root).resolve() if wire_root is not None else None
        self.input_histories.bind_scope(f"comms:{FieldCodec.encode(type(conversation))}:{conversation.input_scope}")
        self.message_contents = ConversationContents()
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
            yield from self.conversation.compose_activity(self)
            pool = self.workspace_composer_pool()
            kind = self.conversation.composer_kind(self)
            if pool is None or not pool.has(kind):
                yield self.conversation.prompt(self).data_bind(
                    project_path=Conversation.project_path,
                    working_directory=Conversation.working_directory,
                    agent_info=Conversation.agent_info,
                    agent_binding=Conversation.agent_binding,
                    status=Conversation.status,
                )

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
            self.settings.ui.message_style(), access=self.app.coordination_access,
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
        if not self.needs_wire_refresh(event.revision):
            return
        self.on_composer("refresh_commands", lambda prompt: prompt.slash_complete.refresh_commands())
        await self._refresh()

    @handles(core_events.SessionSelected)
    async def _selected_source_changed(self, event: core_events.SessionSelected) -> None:
        """A retained view reads current source after its tab opens."""
        self.refresh_identity()
        await self._refresh()

    @handles(LinkContextChanged)
    async def _command_source_changed(self, event: LinkContextChanged) -> None:
        """The sidebar's references changed: the label and commands follow them."""
        await super()._command_source_changed(event)
        self.refresh_identity()

    def attach_pooled_composer(self) -> Prompt | None:
        """Register this chat's first prompt in the shared workspace pool, or check out and
        reparent the pool's live prompt when this chat is the active tab."""
        pool = self.workspace_composer_pool()
        kind = self.conversation.composer_kind(self)
        prompt = self.active_composer
        if prompt is not None:
            if pool is not None and not pool.has(kind):
                prompt._bound_host = self
                pool.register(kind, self, prompt)
            self.flush_composer_applies(prompt)
            return prompt
        if not self.is_attached or not self.query_ancestor(SessionScope).is_current:
            return None
        if pool is not None and pool.has(kind):
            prompt, _reused = pool.acquire(kind, self, lambda: self.conversation.prompt(self))
            stack = self.query_one(PromptStack)
            prompt.reparent(stack)
            self.flush_composer_applies(prompt)
            return prompt
        return None

    def prepare_prompt(self) -> None:
        """Apply comms prompt state after a mode becomes active."""
        prompt = self.attach_pooled_composer()
        if prompt is None:
            # A large Channels panel may mount its virtual rows before the
            # channel composer finishes composing its Prompt. Both its Mount
            # callback and the containing Screen's Mount callback can arrive
            # first; settle once after the committed first layout instead of
            # dereferencing an unmounted getter.
            if self.is_attached and self.query_ancestor(SessionScope).is_current:
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

    LABELS_GROUP = "chat-labels"

    def read_thread_config(self) -> None:
        self.run_worker(self._refresh_thread_config, group=self.LABELS_GROUP)

    def mentions_read(self) -> None:
        self.call_after_refresh(self.message_history.mark_visible)

    def thread_status_shown(self) -> None:
        if self.window.follows_tail:
            self.window.anchor()


    def channel_prompt(self, placeholder: str) -> ChannelPrompt:
        return ChannelPrompt(project=self.project_path, placeholder=placeholder, submissions=self.submissions)

    def message_prompt(self) -> MessagePrompt:
        return MessagePrompt(project=self.project_path, submissions=self.submissions)

    def channel_prompt_kind(self) -> type[ChannelPrompt]:
        return ChannelPrompt

    def message_prompt_kind(self) -> type[MessagePrompt]:
        return MessagePrompt

    def compose_channel_activity(self) -> ComposeResult:
        yield ChannelActivity(self)

    def compose_peer_activity(self, peer: ThreadIncarnation) -> ComposeResult:
        self.thread_activity = ConversationSessionDetails(peer)
        yield self.thread_activity

    def queue_controls_changed(self) -> None:
        """A message view has no goal bar to redraw."""

    def draws_user_message(self, sent) -> bool:
        return self.message_history.draws(sent)
