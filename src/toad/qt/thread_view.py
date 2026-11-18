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

from abc import abstractmethod
from typing import TYPE_CHECKING

from agent_comms.registry.thread_presentation import NoThreadPresentation, ThreadPresentation
from metaclass_registry.mro_dispatch import MroDispatch
import asyncio
from functools import partial

import shiboken6
from agent_comms.ui_model.message_category import all_categories
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming import StatusColorRole

from toad.client.history_state import LatestViewportRequest
from toad.client.reader_position import LatestPosition

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.agent_bound import ObservedAgentBinding
from toad.client.bus_submission import TypedText
from toad.conversation_submission import ConversationSubmissions
from toad.client.session_sources import SessionSources, SourcedConversation
from toad.client.category_selection import CategorySelection
from toad.client.view_settings import ConversationSettingsOwner
from toad.qt.view_settings import QtViewSettings
from toad.navigation_context import ThreadViewNavigation
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.observed_field import ObservedField
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.client.transcript_history_contract import TranscriptHistoryContract
from toad.prompt_actions import SubmitInputAction
from toad.qt.activity import QtObservedSweep
from toad.qt.prompt_stack import QtFlash, QtInputDeliveryDetails, QtSessionDetails
from agent_comms.ui_model.delivery import DeliveryView
from toad.qt.bound_view import QtBoundViewHost
from toad.qt.composer import Composer, ComposerHost
from toad.qt.goal import QtGoalBar
from toad.qt.history import QtHistoryNotifications, QtHistoryWindow
from toad.qt.transcript_history import QtTranscriptHistory
from toad.qt.page import Page
from toad.status_thread import StatusThread, WorkingStatusOwner
from toad.client.prompt_composer import ComposerStatus
from toad.client.prompt_stack import ErrorTone, SuccessTone
from toad.conversation_turn import ConversationTurn
from toad.submission_queue import NoQueueSource, QueueSource
from toad.transcript_publication import BoundView, CanonicalSourcePublication, TranscriptPresentation
from toad.client.history_rows_view import AsyncioPublications, HistoryRowsBlocks, settled
from toad.transcript_scope import TranscriptScope, TranscriptView
from toad.qt.core_events import QtCoreObserver
from toad.qt.draft_line import QtDraftLine
from toad.qt.submission_view import QtSubmissionView
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame

if TYPE_CHECKING:
    from toad.agent_base import AgentBase
    from toad.client.session_tracker import SessionDetails
    from toad.qt.window import QtToadApp


class QtThreadView(
    QtViewSettings,
    CategorySelection,
    WorkingStatusOwner,
    ComposerStatus,
    ConversationSettingsOwner,
    ThreadViewNavigation,
    ObservedAgentBinding,
    ConversationThreadReadMixin,
    ThreadBindingDispatch,
    TranscriptView,
    QtCoreObserver,
    MroDispatch,
    HistoryRowsBlocks,
    AsyncioPublications,
    SourcedConversation,
    QtSubmissionView,
    QtBoundViewHost,
    Page,
    WorkspaceHosted,
    ComposerHost,
    QtHistoryNotifications,
    QWidget,
    metaclass=PyQtWidgetMeta,
):
    """Shared base for Qt views that host a bound thread's transcript.

    Subclasses MUST:
    - Assign `self.app` before calling `self._setup_transcript(app)`.
    - Implement `thread_identity`, `mode`, `origin`, `transcript_scope` per
      SessionScope contract.

    The transcript stack (`messages`, `transcript`, `message_history`), the
    `BoundViewHost` contract, the `ObservedAgentBinding` field (a real
    `AgentConnection` on ACP views, `NoAgentConnection()` on mailbox views), the
    rows under the transcript (`_setup_prompt_stack`) and the composer's input path
    are owned here, so the two thread-bound views share one implementation.
    `WorkingStatusOwner` and `ComposerStatus` are the parents Textual's
    `Conversation` inherits for the working answer and the info bar's status.
    """

    agent_binding: ObservedField[AgentConnection] = ObservedField(NoAgentConnection())



    # ---- Shared contract: the rows Textual's `Conversation.compose` mounts ----
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
    def feedback(self) -> QtFlash:
        """Textual's `Flash`: the centred transient notice ("Agent Comms connected")."""

    @property
    @abstractmethod
    def agent_activity(self) -> QtObservedSweep:
        """Textual's `throbber_above`: the sweep painting `working()`."""

    @property
    @abstractmethod
    def thread_activity(self) -> QtSessionDetails:
        """Textual's `OperationalSessionDetails`: ``▶ <status> · …`` over its details."""

    @property
    @abstractmethod
    def goal_bar(self) -> QtGoalBar | None:
        """Textual's `GoalBar`; `None` for a view with no managed thread to own a goal."""

    @property
    @abstractmethod
    def composer(self) -> "Composer | None":
        """Textual's prompt: the framed ``❯`` editor and its info bar, mounted one Qt
        tick after construction (`None` until the Android first-paint race clears)."""

    @property
    @abstractmethod
    def submissions(self) -> ConversationSubmissions:
        """The owner the composer submits through: Textual's `Conversation.submissions`."""

    @abstractmethod
    def composer_class(self) -> type[Composer]:
        """The composer this view kind mounts (Textual's `operational_sources.prompt`)."""

    def close_core_events(self) -> None:
        """The view's own subscriptions end, and the rows under the transcript stop
        observing with it."""
        super().close_core_events()
        self.thread_activity.close_activity()
        if self.goal_bar is not None:
            self.goal_bar.close_activity()

    def history_loading(self) -> bool:
        """As Textual's `Conversation`: only wire histories page in under a loading row."""
        return False

    def sync_working(self) -> None:
        """Textual's `Conversation.sync_working`: the sweep and the status title read the
        one `working()` answer and the observed row again."""
        self.agent_activity.sync()
        self.thread_activity.refresh_summary()

    def _turn_changed(self, owner) -> None:
        self.sync_working()

    _thread_status: object = ""

    @property
    def thread_status(self):
        return self._thread_status

    @thread_status.setter
    def thread_status(self, status) -> None:
        self._thread_status = status
        self.sync_status()

    def sync_status(self) -> None:
        """The info bar shows `ComposerStatus.composed_status()` once the composer exists."""
        if self.composer is not None:
            self.composer.show_status(self.composed_status())

    def inspect_session(self) -> None:
        """Textual's `Conversation.inspect_session`: the session details over the view, the
        overview from the status row."""
        QtInputDeliveryDetails(
            self, self.app.renderer, self.thread_activity.overview(), DeliveryView()).open()

    def present_thread_status(self) -> None:
        """A native agent reports its configuration through ACP (Textual's
        `OperationalSessionSources.thread_presented`); a CLI thread overrides."""

    def apply_bound_agent(self, agent: "AgentBase") -> None:
        """A late-bound agent: the status thread and working answer are read again."""
        self.refresh_thread_status()
        self.sync_working()

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
        # `NativeSessionEntry.__call__` writes this on tabs that go through the
        # entry; mailbox opens through `replace_opening_view` instead.
        self.session_details: "SessionDetails | None" = None
        # Transcript window + history reader. `QtTranscriptHistory` mirrors
        # Textual's `TranscriptHistory` — same `CommittedHistoryBase` +
        # `ReportsCoveredPages` bases, same `SavedTranscript` source over
        # `view.transcript.get_transcript_page`, same page type
        # (`PreparedTranscriptPage`). Tool calls, sent messages, Claude chunks and
        # context events all feed in through this one source.
        self.messages = QtHistoryWindow(app.renderer, self)
        # `TranscriptPresentation` first: `QtTranscriptHistory._initial_page_source`
        # reads `self.view.transcript.get_transcript_page` during construction to
        # build its `SavedTranscript`, so the attribute has to exist before the
        # history does.
        self.transcript = TranscriptPresentation()
        # The categories this view's transcript shows (`CategorySelection`); the history
        # reads them through `selected_categories` from its first page.
        self.visible_categories = all_categories()
        self.message_history = QtTranscriptHistory(self.messages, self, app)
        self.turns = ConversationTurn(self._turn_changed, lambda: self.agent_binding.presentation.turns)
        # Where input and queue go; the opener swaps in mailbox sources for a CLI thread.
        self.operational_sources = SessionSources()
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
        self.mount_history(self.message_history)
        self.thread_activity.mount()
        if self.goal_bar is not None:
            self.goal_bar.mount()

    def _setup_prompt_stack(self, app: "QtToadApp", layout: QVBoxLayout, incarnation) -> None:
        """Mount, under the transcript, the rows Textual's `Conversation.compose` yields
        after its window, in its order: flash, sweep, session status, goal bar, prompt.

        The composer mounts one Qt event-loop tick later: on Qt-for-Android, mounting
        ``QPlainTextEdit`` during ``__init__`` races ``QtAndroidAccessibility`` with the
        first-paint EGL setup and deadlocks the window. Its slot is reserved here so it
        lands in order. ``submissions`` exists first so ``BusSubmissions.queue_evidence``
        has an owner by the composer's first ``show_submitting``."""
        self.draft_line = QtDraftLine()
        self.feedback = QtFlash(app, app.renderer)
        self.agent_activity = QtObservedSweep(self.working, renderer=app.renderer)
        self.thread_activity = QtSessionDetails(self, app.renderer)
        self.goal_bar = None if incarnation is None else QtGoalBar(app, app.renderer, incarnation)
        self.submissions = ConversationSubmissions(self)
        self.composer = None
        self._composer_slot = QVBoxLayout()
        self._composer_slot.setContentsMargins(0, 0, 0, 0)
        for row in (self.draft_line, self.feedback, self.agent_activity, self.thread_activity, self.goal_bar):
            if row is not None:
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
            print(f"QtThreadView {type(self).__name__} composer mount failed: {error!r}", flush=True)
            import traceback
            traceback.print_exc()
            app.status_line.show_status(f"Composer mount failed: {error}", StatusColorRole.ERROR)
            return
        self._composer_slot.addWidget(self.composer)
        self.composer.labelled(self.composer_label)
        self.sync_status()

    @property
    @abstractmethod
    def composer_label(self) -> str:
        """What the composer's placeholder names."""

    # ---- ComposerHost contract: `app`, `submissions`, `submit`, `update_slash_commands` ----

    def submit(self, text: TypedText, action: SubmitInputAction) -> None:
        """The composer's input enters the view's submissions, as Textual's prompt's
        `UserInputSubmitted` reaches `Conversation.submissions.submit`; shell-prefix detection
        matches `conversation.py`."""
        body = text.text
        event = action.submission_event(body[1:] if body.startswith("!") else body, body.startswith("!"))
        self.run_worker(partial(self.submissions.submit, event), group="submit", exclusive=False)

    def update_slash_commands(self) -> None:
        """Called by the composer when the user starts typing a slash command.
        The session lifecycle will replace this with the real ``CommandCatalog``
        pull."""
        if self.composer is None:
            return
        self.composer.set_commands([])

    async def command_target_context(self):
        """Shared `ConversationCommands` contract: the target context a slash
        command runs against. Both frontends route through
        `page_source.command_context(view)`; Textual's `comms_chat.MessageView`
        at line 349 is the mirror. The page source owns per-thread targeting
        semantics; this base just delegates.

        Returns None if the transcript stack hasn't been wired yet — a slash
        command typed before mount simply has no context to publish against.
        """
        source = getattr(self.message_history, "page_source", None)
        if source is None:
            return None
        return source.command_context(self)

    async def read_command_catalog(self):
        """Shared `ConversationCommands` contract: the slash-command catalog
        this conversation offers, read fresh on each completion. Textual's
        implementation lives on `Conversation.read_command_catalog`
        (`src/toad/widgets/conversation.py:1746`); same shape here. The agent
        binding carries the advertised commands; `command_target_context` is
        awaited inside `CommandCatalog.read` to project applicability."""
        from toad.command_catalog import CommandCatalog

        agent = self.agent_binding
        context = self.command_target_context()
        return await CommandCatalog.read(
            self.app, agent.presentation.commands, context, self.local_commands
        )

    def flash(self, text: str) -> None:
        """Shared `FlashHost` contract, drawn by Textual's `Flash` sibling."""
        self.feedback.flash(text)

    def flash_success(self, text: str) -> None:
        self.feedback.flash(text, style=SuccessTone.declared_name)

    def flash_error(self, text: str) -> None:
        self.feedback.flash(text, style=ErrorTone.declared_name)


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
    def contents(self) -> "QtThreadView":
        """`BoundViewHost.contents`: the view widget itself holds the transcript blocks
        (its `message_history`), so `BoundView.current` reads this view's attachment."""
        return self

    @property
    def transcript_history(self) -> TranscriptHistoryContract:
        """`BoundViewHost.transcript_history`: the single transcript-page-producing
        child `BoundView` drives. `QtTranscriptHistory` satisfies the contract
        through the shared `CommittedHistoryBase` + `ReportsCoveredPages` bases."""
        return self.message_history

    # ---- BoundViewHost: Qt draws the blocks as rows of its one history model ----

    def show_draft(self, draft, identity) -> None:
        self.draft_line.show_draft(draft)

    def empty_history(self) -> QtTranscriptHistory:
        return QtTranscriptHistory(self.messages, self, self.app)

    def mount_history(self, history, *, before=None):
        self.message_history = history
        history.observe_source()
        history.state.mounted(history)
        return settled()

    def remove_history(self, history):
        history.close()
        return settled()

    def call_later(self, callback, *args) -> bool:
        if not self.is_attached:
            return False
        QTimer.singleShot(0, partial(callback, *args))
        return True

    def after_refresh(self, callback) -> None:
        QTimer.singleShot(0, callback)

    def history_painted(self) -> None:
        self.submissions.settle()

    def refresh_session_summary(self) -> None:
        self.thread_activity.refresh_summary()

    def resume_retained_history(self) -> None:
        self.message_history.state.resume_if_parked(self.message_history)

    # ---- TranscriptView ----

    def transcript_changed(self) -> None:
        """The thread's source changed outside this view: publish its canonical source
        again — the request Textual's `OperationalSessionSources` makes for it."""
        self.transcript.source_requests.request(CanonicalSourcePublication)

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
        self.refresh_thread_status()
        self.present_thread_status()
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

    def categories_changed(self) -> None:
        self.message_history.apply_filter()

    @property
    def configuration_identity(self):
        return self.app.session_navigation.get(self.mode).identity

    @property
    def configuration_settings(self):
        return self.app.saved_settings

    @property
    def navigation_mode(self) -> str:
        return self.mode

    @property
    def navigation_project(self):
        return self.app.project_dir

    @property
    def coordination_root(self) -> str | None:
        return self.thread_identity.wire_root()


    @property
    def is_attached(self) -> bool:
        """True until the Qt widget tears down. `BoundView.thread_scope` gates its
        subscription on this flag; Textual's `Widget.is_attached` fills the same
        role. A widget whose C++ side Qt already deleted is not attached: asking it
        anything else would dereference the freed object."""
        return shiboken6.isValid(self) and (self.isVisible() or self.parent() is not None)

    @property
    def is_leaving(self) -> bool:
        return not self.is_attached

    @property
    def is_current_session(self) -> bool:
        """Whether this view is the one on screen. `_publish_thread_source` gates
        its request on this so hidden tabs stash the presentation for next show."""
        selected = self.app.workspace_sessions.selected
        return selected is self
