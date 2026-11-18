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
from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.category_selection import CategorySelection
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.observed_field import ObservedField
from toad.client.resource_release import ResourceRelease
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
from toad.transcript_publication import BoundView, TranscriptPresentation
from toad.transcript_scope import TranscriptScope
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame

if TYPE_CHECKING:
    from toad.agent_base import AgentBase
    from toad.client.session_tracker import SessionDetails
    from toad.qt.window import QtToadApp


class QtThreadView(
    CategorySelection,
    WorkingStatusOwner,
    ComposerStatus,
    ObservedAgentBinding,
    ConversationThreadReadMixin,
    ThreadBindingDispatch,
    MroDispatch,
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

    # ``BusSubmissions.queue_evidence`` reads ``self.view.queue_source`` on the
    # composer's first ``show_submitting``. Default until a view wires a live
    # ``NativeQueueSource`` — ``ConversationView``, ``QtAcpSessionView`` and
    # ``CommsChatView`` all used the same default; hoisted here so both thread
    # views inherit it. Subclasses with a live queue binding override.
    queue_source: QueueSource = NoQueueSource()

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
    def submissions(self) -> BusSubmissions:
        """``BusSubmissions`` — the owner the composer publishes through on ``submit``."""

    @abstractmethod
    def composer_class(self) -> type[Composer]:
        """The composer this view kind mounts (Textual's `operational_sources.prompt`)."""

    def close_core_events(self) -> None:
        """The rows under the transcript stop observing with the view."""
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
        self.messages = QtHistoryWindow(app.renderer)
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
        # Bind once message_history exists: `BoundView` reads
        # `self.transcript_history` immediately.
        self.transcript.bind(self)
        # Textual's `TranscriptHistory.on_mount` observes the source and loads the first
        # page; Qt has no mount event, so the load runs one tick after the view is placed.
        QTimer.singleShot(0, self._start_transcript_source)

    def _setup_prompt_stack(self, app: "QtToadApp", layout: QVBoxLayout, incarnation) -> None:
        """Mount, under the transcript, the rows Textual's `Conversation.compose` yields
        after its window, in its order: flash, sweep, session status, goal bar, prompt.

        The composer mounts one Qt event-loop tick later: on Qt-for-Android, mounting
        ``QPlainTextEdit`` during ``__init__`` races ``QtAndroidAccessibility`` with the
        first-paint EGL setup and deadlocks the window. Its slot is reserved here so it
        lands in order. ``submissions`` exists first so ``BusSubmissions.queue_evidence``
        has an owner by the composer's first ``show_submitting``."""
        self.feedback = QtFlash(app, app.renderer)
        self.agent_activity = QtObservedSweep(self.working, renderer=app.renderer)
        self.thread_activity = QtSessionDetails(self, app.renderer)
        self.goal_bar = None if incarnation is None else QtGoalBar(app, app.renderer, incarnation)
        self.submissions = BusSubmissions(self)
        self.composer = None
        self._composer_slot = QVBoxLayout()
        self._composer_slot.setContentsMargins(0, 0, 0, 0)
        for row in (self.feedback, self.agent_activity, self.thread_activity, self.goal_bar):
            if row is not None:
                layout.addWidget(row)
        layout.addLayout(self._composer_slot)
        if self.goal_bar is not None:
            # The bar hides itself until a goal is read, so it cannot wait for showEvent.
            self.goal_bar._attach_observation_if_needed()
        self.thread_activity.mount()
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
        """Publish ``UserInputSubmitted`` through Core's event stream — the same
        payload Textual's prompt publishes at ``widgets/conversation.py:901-904``.
        A listening backend ``Conversation`` picks it up and routes through its
        ``ConversationSubmissions`` family. If no backend is listening, the
        submit silently vanishes; the composer reflects that visibly through its
        ``show_submitting`` state until the queue reader catches up. Shell-prefix
        detection matches ``conversation.py:900``."""
        body = text.text
        event = action.submission_event(body[1:] if body.startswith("!") else body, body.startswith("!"))
        try:
            self.app.events.publish(event)
        except Exception as error:
            if self.composer is not None:
                self.composer.show_failure(f"Send failed: {error}")
                self.composer.restore_draft(body)
            return
        if self.composer is not None:
            self.composer.show_submitting()

    def submissions_changed(self) -> None:
        """``BusSubmissions.publish_pending`` calls this when the queue changes."""
        if self.composer is None:
            return
        self.composer.show_submitting()

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


    def _start_transcript_source(self) -> None:
        """Deferred transcript source start: fires on the next Qt event-loop tick,
        after the view has mounted into the workspace stack.

        Direct `await jump_latest(...)` here — not `load_initial_page` →
        `request_latest` → `state.schedule_source_work` — because the scheduled
        work path does not populate rows during the initial swap-in on Qt
        (the RunningSourceWork task either doesn't get pumped before the first
        viewport read or its paint result is dropped). Direct await drives the
        same jump_latest body we probed working with 9+ rows on a mailbox tap.
        `observe_source` still runs so the pager tracks the history on its
        window for subsequent revision ticks.
        """
        self.message_history.observe_source()
        request = LatestViewportRequest(LatestPosition.hold(self.message_history.window))
        task = asyncio.ensure_future(self.message_history.jump_latest(request))
        task.add_done_callback(self._initial_load_done)

    def _initial_load_done(self, task: asyncio.Task) -> None:
        """Report any exception from the initial page load so a failed first
        fetch is visible instead of silently leaving the transcript blank.

        An empty transcript after a clean load is ALSO reported — a view that
        paints a black body with no rows is not a success story."""
        if task.cancelled():
            print(f"QtThreadView {type(self).__name__} initial load cancelled", flush=True)
            return
        exc = task.exception()
        if exc is not None:
            import traceback
            print(f"QtThreadView {type(self).__name__} initial transcript load failed: {exc!r}", flush=True)
            traceback.print_exception(exc)
            return
        try:
            model = self.messages.model() if hasattr(self.messages, "model") else None
            rows = model.rowCount() if model is not None else -1
        except RuntimeError:
            # View torn down between done-callback scheduling and running —
            # nothing to report, the user already closed this view.
            return
        if rows <= 0:
            # Loud only when the load produced nothing — a view that paints a
            # black body with no rows is the failure case the diagnostic targets.
            source = getattr(self.message_history, "page_source", None)
            print(
                f"QtThreadView {type(self).__name__} initial load empty: "
                f"rows={rows} source={type(source).__name__ if source else None}",
                flush=True,
            )

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
