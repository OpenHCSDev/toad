"""Shared Qt base for views that render a bound thread's transcript.

Both `QtAcpSessionView` (live Claude-CLI session) and `QtMailboxView` (saved
mailbox thread opened through `thread_navigation.open`) render the same
transcript machinery: a `QtHistoryWindow` scrolling a `QtTranscriptHistory`
bound to a `TranscriptPresentation`, with the shared `ThreadBindingDispatch`
routing `thread_observed` updates and a `QtAgentActivity` ribbon showing
when the agent is working.

This base owns that stack so neither view handrolls it. Subclass-specific
responsibilities stay on each view: ACP carries the agent binding + composer
for live sends, mailbox carries the mailbox lifecycle hooks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.registry.thread_presentation import NoThreadPresentation, ThreadPresentation
from metaclass_registry.mro_dispatch import MroDispatch
from PySide6.QtWidgets import QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.agent_bound import ObservedAgentBinding
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.observed_field import ObservedField
from toad.client.resource_release import ResourceRelease
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.client.transcript_history_contract import TranscriptHistoryContract
from toad.qt.agent_activity import QtAgentActivity
from toad.qt.bound_view import QtBoundViewHost
from toad.qt.history import QtHistoryWindow
from toad.qt.transcript_history import QtTranscriptHistory
from toad.qt.page import Page
from toad.status_thread import StatusThread
from toad.transcript_publication import BoundView, TranscriptPresentation
from toad.transcript_scope import TranscriptScope
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame

if TYPE_CHECKING:
    from toad.agent_base import AgentBase
    from toad.client.session_tracker import SessionDetails
    from toad.qt.window import QtToadApp


class QtThreadView(
    ObservedAgentBinding,
    ConversationThreadReadMixin,
    ThreadBindingDispatch,
    MroDispatch,
    QtBoundViewHost,
    Page,
    WorkspaceHosted,
    QWidget,
    metaclass=PyQtWidgetMeta,
):
    """Shared base for Qt views that host a bound thread's transcript.

    Subclasses MUST:
    - Assign `self.app` before calling `self._setup_transcript(app)`.
    - Implement `thread_identity`, `mode`, `origin`, `transcript_scope` per
      SessionScope contract.

    The transcript stack (`self.messages`, `self.transcript`,
    `self.message_history`, `self.agent_activity`) and the `BoundViewHost`
    contract (`window`, `contents`, `transcript_history`, `transcript_binding`)
    are owned here so there is one source for the Qt transcript rendering.

    Also provides the `ObservedAgentBinding` wiring (`agent_binding`
    ObservedField + change watchers) so both views share the shape Textual's
    `Conversation.watch_agent_binding` plays. ACP views (live session) will
    write a real `AgentConnection` into `self.agent_binding`; mailbox views
    (saved history) leave it as `NoAgentConnection()` and still render from
    the transcript scope.
    """

    # Shared `ObservedAgentBinding` storage: the `ObservedField` descriptor on
    # `AgentBoundConversation` requires each concrete class to provide one. Previously
    # `QtAcpSessionView` and `QtMailboxView` each declared their own identical
    # `agent_binding = ObservedField(NoAgentConnection())`. Hoisted here so there is
    # one owner — subclasses stop duplicating it.
    agent_binding: ObservedField[AgentConnection] = ObservedField(NoAgentConnection())

    def apply_bound_agent(self, agent: "AgentBase") -> None:
        """Default no-op: `ObservedAgentBinding.bind_agent` calls this after storing.
        ACP views override to update their composer / identity line / status;
        mailbox views have no bound agent and inherit the no-op."""

    def agent_connected(self, agent: "AgentBase") -> None:
        """Default no-op: flash notice on connect. ACP views override; mailbox
        views have no connect event and inherit the no-op."""

    def _setup_transcript(self, app: "QtToadApp") -> None:
        """Build the transcript stack. Call from the subclass `__init__` after
        `super().__init__()` and after assigning `self.app`.

        Mirrors the transcript setup in `QtAcpSessionView.__init__` (lines 215-229
        at the time of extraction) — same ordering (TranscriptPresentation before
        QtTranscriptHistory because the history reads `view.transcript.get_transcript_page`
        during construction), same instances, same bind.
        """
        # ThreadBindingDispatch state: current observed + any arrived while this
        # view was not the selected session. Textual's `Conversation` declares these
        # as class attributes; the instance init here keeps the same shape for both
        # subclasses.
        self.thread_presentation: ThreadPresentation = NoThreadPresentation()
        self._unpublished_presentation: ThreadPresentation = NoThreadPresentation()
        self._thread_observation = ResourceRelease()
        # `NativeSessionEntry.__call__` writes this on tabs that go through the
        # entry; mailbox opens through `replace_opening_view` instead.
        self.session_details: "SessionDetails | None" = None
        # Transcript window + history reader. `QtTranscriptHistory` mirrors
        # Textual's `TranscriptHistory` — same `CommittedHistoryBase` +
        # `ReportsCoveredPages` bases, same `SavedTranscript` source over
        # `view.transcript.get_transcript_page`, same page type
        # (`PreparedTranscriptPage`). Tool calls, sent messages, Claude chunks and
        # context events all feed in through this one source.
        self.messages = QtHistoryWindow(app.renderer.scheme)
        # `TranscriptPresentation` first: `QtTranscriptHistory._initial_page_source`
        # reads `self.view.transcript.get_transcript_page` during construction to
        # build its `SavedTranscript`, so the attribute has to exist before the
        # history does.
        self.transcript = TranscriptPresentation()
        self.message_history = QtTranscriptHistory(self.messages, self, app)
        # Activity sweep above the transcript — Qt sibling of Textual's
        # `Conversation.throbber_above = AboveThrobber(self.working)`. Reads the
        # shared `TurnOwner.busy` via a `ConversationTurn` and animates the shared
        # `ACTIVITY_SWEEP` ribbon.
        self.agent_activity = QtAgentActivity(self, app.renderer)
        # Bind once message_history exists: `BoundView` reads
        # `self.transcript_history` immediately.
        self.transcript.bind(self)

    # ---- BoundViewHost contract ----

    @property
    def screen(self) -> WorkspaceFrame:
        return QWidget.window(self)

    @property
    def window(self) -> QtHistoryWindow:
        """`BoundViewHost.window`: the scroll surface. `BoundView` reads
        `window.scroll_revision` + `window.is_attached` to tell when a paint
        happened. Shadows the inherited `QWidget.window` callable — screen access
        routes through `QWidget.window(self)` in `self.screen`."""
        return self.messages

    @property
    def contents(self) -> "QtBoundViewHost":
        """`BoundViewHost.contents`: a `ChildrenOwner`. Self is the view widget
        inheriting `QtChildrenOwner` through `QtBoundViewHost`; its `findChildren`
        sees the whole tab including `message_history`."""
        return self

    @property
    def transcript_history(self) -> TranscriptHistoryContract:
        """`BoundViewHost.transcript_history`: the single transcript-page-producing
        child `BoundView` drives. `QtTranscriptHistory` satisfies the contract
        through the shared `CommittedHistoryBase` + `ReportsCoveredPages` bases."""
        return self.message_history

    def transcript_binding(self) -> BoundView:
        """Called by `ViewBinding.bound_to(view)` on `TranscriptPresentation.bind`.
        Returns a `BoundView` that routes transcript events into this view through
        the `BoundViewHost` surface above."""
        return BoundView(self)

    # ---- ThreadBindingDispatch ----

    def thread_presented(self, presentation: ThreadPresentation) -> None:
        """A settled member owns whether this view has source work to publish.
        Mirrors `Conversation.thread_presented` at `widgets/conversation.py:972` —
        same shape, skipping the Textual `operational_sources` leg."""
        self.thread_presentation = presentation
        self.dispatch_sync(presentation)

    # ---- thread_scope / status_thread for ConversationThreadReadMixin ----

    @property
    def thread_scope(self) -> TranscriptScope:
        """The transcript scope this view is currently bound to. Mirrors
        `Conversation.thread_scope` at `widgets/conversation.py:970`. Returns
        `NoTranscript` when unbound (via the BoundView's own gate at
        `transcript_publication.py:742`)."""
        return self.transcript.binding.thread_scope

    def status_thread(self) -> StatusThread:
        """`ConversationThreadReadMixin.consume_thread_presentation` reads this to
        open the thread's status by name. Mirrors Textual's
        `Conversation.status_thread` at `widgets/conversation.py:976`. Unbound views
        get `NoStatusThread` (name='') via the NoTranscript path, so the first
        bind runs cleanly before the view is attached."""
        return self.thread_scope.status_thread(self.app.coordination_access)

    # ---- attached / current session ----

    @property
    def is_attached(self) -> bool:
        """True until the Qt widget tears down. `BoundView.thread_scope` gates its
        subscription on this flag; Textual's `Widget.is_attached` fills the same
        role."""
        try:
            return self.isVisible() or self.parent() is not None
        except RuntimeError:
            return False

    @property
    def is_leaving(self) -> bool:
        return not self.is_attached

    @property
    def is_current_session(self) -> bool:
        """Whether this view is the one on screen. `_publish_thread_source` gates
        its request on this so hidden tabs stash the presentation for next show."""
        selected = self.app.workspace_sessions.selected
        return selected is self
