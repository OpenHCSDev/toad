"""The Qt thread layer: a conversation that shows a bound thread's transcript.

Both `QtAcpSessionView` (live Claude-CLI session) and `QtMailboxView` (saved mailbox thread
opened through `thread_navigation.open`) are a `QtConversation` whose history is a
`QtTranscriptHistory` bound to a `TranscriptPresentation`: the transcript publishes through
`BoundView`, so this layer answers `BoundViewHost`, and under it sit the rows Textual's
`Conversation.compose` mounts for a thread (session status, goal bar, prompt). The channel
tab, `ConversationView`, is the other `QtConversation`: its wire history publishes no
transcript.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from agent_comms.messaging.channel_targets import CommandTarget
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from agent_comms.ui_model.delivery import DeliveryView
from toad.client.draft_fragments import DRAFT_FRAGMENTS
from toad.client.history_rows_view import HistoryRowsBlocks, settled
from toad.client.transcript_history_contract import TranscriptHistoryContract
from toad.navigation_context import ThreadViewNavigation
from toad.qt.bound_view import QtBoundViewHost
from toad.qt.composer import Composer
from toad.qt.conversation import QtConversation
from toad.qt.goal import QtGoalBar
from toad.qt.history import QT_FRAGMENT_CLASSES
from toad.qt.prompt_stack import QtInputDeliveryDetails, QtSessionDetails
from toad.qt.question import QtQuestion
from toad.qt.transcript_history import QtTranscriptHistory
from toad.target_commands import TargetContext
from toad.transcript_publication import BoundView

if TYPE_CHECKING:
    from toad.client.session_tracker import SessionDetails
    from toad.qt.window import QtToadApp


class QtThreadView(
    QtConversation,
    ThreadViewNavigation,
    HistoryRowsBlocks,
    QtBoundViewHost,
    metaclass=PyQtWidgetMeta,
):
    """A `QtConversation` showing one bound thread's transcript.

    Subclasses MUST assign `self.app` before calling `self._setup_transcript(app)`, and
    answer `thread_identity`, `mode`, `origin` and `transcript_scope`.

    The transcript stack (`message_history` over `transcript`), the `BoundViewHost`
    contract and the thread's rows under the transcript (`_setup_prompt_stack`) are owned
    here, so the two thread-bound views share one implementation.
    """

    # ---- Shared contract: the rows Textual's `Conversation.compose` mounts for a thread ----
    #
    # Under the transcript Textual yields `Flash`, then its `PromptStack`: the activity
    # sweep (`throbber_above`), the session-status disclosure (`thread_activity`), the
    # goal bar and the prompt (with its info bar). `_setup_prompt_stack` mounts the Qt
    # sibling of each in that order. Each is an abstract property so a subclass that
    # omits one fails at instantiation (`TypeError` listing every missing name); the
    # subclass satisfies it with a class-level `None` and the base assigns the widget.

    @property
    @abstractmethod
    def identity_line(self) -> QWidget:
        """The banner / title row every thread view shows at the top of its layout."""

    @property
    @abstractmethod
    def thread_activity(self) -> QtSessionDetails:
        """Textual's `OperationalSessionDetails`: ``▶ <status> · …`` over its details."""

    @property
    @abstractmethod
    def goal_bar(self) -> QtGoalBar | None:
        """Textual's `GoalBar`; `None` for a view with no managed thread to own a goal."""

    @abstractmethod
    def composer_class(self) -> type[Composer]:
        """The composer this view kind mounts (Textual's `operational_sources.prompt`)."""

    @property
    @abstractmethod
    def composer_label(self) -> str:
        """What the composer's placeholder names."""

    def sync_working(self) -> None:
        """Textual's `Conversation._turn_changed`: the sweep, then the session details
        read the observed row again."""
        super().sync_working()
        self.thread_activity.refresh_summary()

    def inspect_session(self) -> None:
        """Textual's `Conversation.inspect_session`: the session details over the view, the
        overview from the status row."""
        QtInputDeliveryDetails(
            self, self.app.renderer, self.thread_activity.overview(), DeliveryView()).open()

    def _setup_transcript(self, app: "QtToadApp") -> None:
        """Build the conversation and its transcript stack. Call from the subclass
        `__init__` after `super().__init__()` and after assigning `self.app`.

        `TranscriptPresentation` (made by `_setup_conversation`) comes before
        `QtTranscriptHistory`: the history reads `view.transcript.get_transcript_page`
        during construction to build its `SavedTranscript`.
        """
        self._setup_conversation(app)
        # `NativeSessionEntry.__call__` writes this on tabs that go through the
        # entry; mailbox opens through `replace_opening_view` instead.
        self.session_details: "SessionDetails | None" = None
        # `QtTranscriptHistory` mirrors Textual's `TranscriptHistory` — same
        # `CommittedHistoryBase` + `ReportsCoveredPages` bases, same `SavedTranscript`
        # source over `view.transcript.get_transcript_page`, same page type
        # (`PreparedTranscriptPage`). Tool calls, sent messages, Claude chunks and
        # context events all feed in through this one source.
        self.message_history = QtTranscriptHistory(self.messages, self, app)
        # Qt has no mount event: the view mounts one event-loop tick later, after the
        # opener has bound its identity (`session_navigation.bind_opened`).
        QTimer.singleShot(0, self._mount_transcript)

    def _mount_transcript(self) -> None:
        """Bind the transcript and mount its history, in the order Textual's mounts run:
        `Conversation.on_mount` binds, then `TranscriptHistory.on_mount` observes the source
        and lets the history's state schedule its first page through `BoundView`.

        Binding observes the view's thread scope, so it waits for the mount: a mailbox view
        learns its thread in `bind_thread`, after construction."""
        if not self.is_attached:
            return
        self.transcript.bind(self)
        self.attach_history(self.message_history)
        for row in self.activity:
            row.mount()

    def _setup_prompt_stack(self, app: "QtToadApp", layout: QVBoxLayout, incarnation) -> None:
        """Mount, under the transcript, the rows Textual's `Conversation.compose` yields
        after its window, in its order: flash, sweep, session status, goal bar, prompt.

        The composer mounts one Qt event-loop tick later: on Qt-for-Android, mounting
        ``QPlainTextEdit`` during ``__init__`` races ``QtAndroidAccessibility`` with the
        first-paint EGL setup and deadlocks the window. Its slot is reserved here so it
        lands in order."""
        self.thread_activity = QtSessionDetails(self, app.renderer)
        self.goal_bar = None if incarnation is None else QtGoalBar(app, app.renderer, incarnation)
        self.activity = tuple(row for row in (self.thread_activity, self.goal_bar) if row is not None)
        self._composer_slot = QVBoxLayout()
        self._composer_slot.setContentsMargins(0, 0, 0, 0)
        for row in (self.feedback, self.agent_activity, *self.activity):
            layout.addWidget(row)
        layout.addLayout(self._composer_slot)
        self.refresh_thread_status()
        QTimer.singleShot(0, lambda: self._mount_composer(app))

    def _mount_composer(self, app: "QtToadApp") -> None:
        """Deferred composer mount; see `_setup_prompt_stack`. A failed mount is loud:
        a silently-missing composer is how the mailbox view first shipped."""
        try:
            self.composer = self.composer_class()(self, app.renderer)
        except Exception as error:
            app.show_error(error, "Composer mount failed")
            return
        self._composer_slot.addWidget(self.composer)
        # Under the composer, as on a channel: the question an agent asks (a permission, a
        # confirmation), hidden until asked.
        self.question = QtQuestion(app, self)
        self._composer_slot.addWidget(self.question)
        self.composer.labelled(self.composer_label)
        self.sync_status()

    async def command_target_context(self) -> TargetContext:
        """Textual's `Conversation.command_target_context`: commands address this view's
        thread, read on the observed root, in its navigation's project and tab."""
        observed = self.app.coordination_access.observation.observed()
        navigation = self.navigation_context
        return self.thread_identity.command_target(
            lambda actor: TargetContext(
                self.app, observed, CommandTarget.named(actor), actor, navigation.project_path,
                navigation.owner_mode))

    # ---- BoundViewHost contract ----

    @property
    def transcript_history(self) -> TranscriptHistoryContract:
        """`BoundViewHost.transcript_history`: the single transcript-page-producing
        child `BoundView` drives. `QtTranscriptHistory` satisfies the contract
        through the shared `CommittedHistoryBase` + `ReportsCoveredPages` bases."""
        return self.message_history

    # ---- BoundViewHost: Qt draws the blocks as rows of its one history model ----

    def show_draft(self, draft, identity) -> None:
        self.messages.show_draft(DRAFT_FRAGMENTS.project_value(draft, identity, QT_FRAGMENT_CLASSES))

    def empty_history(self) -> QtTranscriptHistory:
        return QtTranscriptHistory(self.messages, self, self.app)

    def attach_history(self, history) -> None:
        """The history becomes the view's one history: it observes its source and its state
        schedules the first page. Qt applies this at once, so there is nothing to wait for."""
        self.message_history = history
        history.observe_source()
        history.state.mounted(history)

    def mount_history(self, history, *, before=None):
        """`BoundViewHost.mount_history`: `BoundView` awaits the mount it asks for."""
        self.attach_history(history)
        return settled()

    def remove_history(self, history):
        history.close()
        return settled()

    def history_painted(self) -> None:
        self.submissions.settle()

    def refresh_session_summary(self) -> None:
        self.thread_activity.refresh_summary()

    def resume_retained_history(self) -> None:
        self.message_history.state.resume_if_parked(self.message_history)

    def transcript_binding(self) -> BoundView:
        """Called by `ViewBinding.bound_to(view)` on `TranscriptPresentation.bind`: a
        thread publishes its transcript through this view, as Textual's
        `Conversation.transcript_binding`."""
        return BoundView(self)

    # ---- ThreadViewNavigation ----

    @property
    def navigation_mode(self) -> str:
        return self.mode

    @property
    def coordination_root(self) -> str | None:
        """The bus root this view's thread is read from, as `SessionScope` answers it."""
        return self.thread_identity.wire_root()
