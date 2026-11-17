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
import asyncio

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.client.history_state import LatestViewportRequest
from toad.client.reader_position import LatestPosition

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.agent_bound import ObservedAgentBinding
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.observed_field import ObservedField
from toad.client.resource_release import ResourceRelease
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.client.transcript_history_contract import TranscriptHistoryContract
from toad.qt.agent_activity import QtAgentActivity
from toad.qt.bound_view import QtBoundViewHost
from toad.qt.goal import QtGoalBar
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


_CONTRACT_MISSING = object()


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

    # ---- Shared contract: fields every concrete thread view must have populated ----
    #
    # Textual's `Conversation` always mounts: transcript, composer (prompt), agent
    # activity ribbon, goal bar, identity line, flash / notice surface, bus submissions.
    # A Qt subclass that omits any of these silently paints a broken screen — the
    # mailbox-composer-missing bug (Nov 17 2026) was exactly that: no error, no log,
    # just no input box, caught only by Tristan looking at a screencap.
    #
    # Each name here must be an instance attribute (or inherited descriptor) set to
    # a non-None value by the time the post-init contract check fires. A missing or
    # None field prints a loud diagnostic to stderr naming the subclass and the field,
    # so the next thing a developer sees is the map — not a silent wrong screen.
    #
    # Fields `_setup_transcript` populates (messages, transcript, message_history,
    # agent_activity) are not listed because the base owns them. The list is the
    # SUBCLASS'S promise to the user, not to the base.
    _REQUIRED_POST_INIT_FIELDS: tuple[str, ...] = (
        "identity_line",   # the banner / title row every thread view shows
        "composer",        # the input box (ACP has it, mailbox silently omitted it pre-fix)
        "submissions",     # BusSubmissions — bus layer the composer sends through
    )

    def __init_subclass__(cls, **kwargs) -> None:
        """Wrap every concrete subclass's ``__init__`` so the shared contract check
        fires after the subclass has built its own state. The check is scheduled on
        the Qt event loop (``QTimer.singleShot(0, ...)``) so a composer mounted lazily
        on the next tick — the pattern on Android to avoid the ComposerEditor /
        a11y race — satisfies the check when it lands, not before.
        """
        super().__init_subclass__(**kwargs)
        original_init = cls.__init__

        def wrapped_init(self, *args, **kw):
            original_init(self, *args, **kw)
            # Defer long enough for lazy composer mounts (QTimer.singleShot(0)) to land.
            # 500 ms gives the first Android paint plenty of room.
            QTimer.singleShot(500, lambda: self._verify_shared_contract())

        wrapped_init.__wrapped__ = original_init  # type: ignore[attr-defined]
        cls.__init__ = wrapped_init

    def _verify_shared_contract(self) -> None:
        """Loud-log every ``_REQUIRED_POST_INIT_FIELDS`` entry this view has not
        populated. Does not raise — the diagnostic is the point; the UI stays up
        so the viewer sees the specific partial state and the logcat names the
        gap. Each missing field prints one line, so a cascade of missing fields
        prints a cascade of lines (what Tristan wanted: ``error changes = here,
        here, here, here — tells you the map``).
        """
        import sys as _sys
        try:
            attached = self.is_attached
        except Exception:
            attached = False
        if not attached:
            return
        for field in self._REQUIRED_POST_INIT_FIELDS:
            value = getattr(self, field, _CONTRACT_MISSING)
            if value is _CONTRACT_MISSING:
                print(
                    f"QtThreadView contract violation: {type(self).__name__} "
                    f"never declared '{field}' — see QtThreadView._REQUIRED_POST_INIT_FIELDS",
                    file=_sys.stderr,
                    flush=True,
                )
            elif value is None:
                print(
                    f"QtThreadView contract violation: {type(self).__name__}.{field} "
                    f"is None 500ms after __init__ — expected a concrete widget / owner",
                    file=_sys.stderr,
                    flush=True,
                )

    def apply_bound_agent(self, agent: "AgentBase") -> None:
        """Default no-op: `ObservedAgentBinding.bind_agent` calls this after storing.
        ACP views override to update their composer / identity line / status;
        mailbox views have no bound agent and inherit the no-op."""

    def agent_connected(self, agent: "AgentBase") -> None:
        """Default no-op: flash notice on connect. ACP views override; mailbox
        views have no connect event and inherit the no-op."""

    # ---- HistoryNotifications hooks ----
    # `QtTranscriptHistory` calls `self.notification_view.check_notifications()` via
    # `prepare_viewport`. ConversationView mixes in `HistoryNotifications` which
    # supplies the method chain; QtAcpSessionView / QtMailboxView don't carry that
    # mixin and would AttributeError on page prep. Default no-ops here keep the
    # transcript pipeline running; a future PR can hoist the real HistoryNotifications
    # mixin onto QtThreadView if mailbox / ACP views ever need live notification
    # tracking of the transcript pages they render.

    def check_notifications(self) -> None:
        """Default no-op; see class docstring. Transcript-rendering Qt views have no
        bus notification surface yet (the notifications are Core-side)."""

    def check_notifications_after_refresh(self) -> None:
        """Default no-op; see `check_notifications`."""

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
        # Trigger the initial page load. Textual's `TranscriptHistory.on_mount`
        # does `_finish_mount()` (which calls `observe_source`) + `state.mounted(self)`
        # (which schedules `load_initial_page` via `call_after_refresh`). Qt has no
        # mount event — the view is constructed-and-shown synchronously — so we
        # defer with QTimer.singleShot(0, ...) to let the view mount into the
        # workspace first; then observe_source() + state.mounted() kick off the
        # SavedTranscript read via the shared pager, which populates `self.messages`
        # with the real transcript pages. Without this call, `self.message_history`
        # would sit with its empty_page and never request pages from the bound
        # transcript scope, which is why mailbox views used to render a black body
        # even when `transcript.binding.thread_scope` resolved to the real
        # `KnownTranscript`.
        QTimer.singleShot(0, self._start_transcript_source)

    def _mount_goal_bar(self, app: "QtToadApp", incarnation) -> QtGoalBar | None:
        """Construct the goal strip that sits above the chat on the TUI.

        The subclass passes the `ThreadIncarnation` the view is bound to (mailbox
        carries one as an `__init__` arg; ACP reads
        `self._agent_binding.initial_identity(...).optional_thread_incarnation()`).
        `None` means this view has no managed-thread goal to show, and the goal
        bar is skipped — a polymorphic branch through
        `SessionIdentity.optional_thread_incarnation`, not an `isinstance` guard.

        Returns the widget for the subclass to place in its own layout slot
        (ACP: above the composer; mailbox: above `self.agent_activity`).

        The bar drives its own visibility through `present_state → setVisible`
        off the thread's `GoalDisplay`: when the goal is unset it takes no
        layout space, matching Textual's `ComposedWhenShown` goal bar.
        """
        if incarnation is None:
            self.goal_bar = None
            return None
        self.goal_bar = QtGoalBar(app, app.renderer, incarnation)
        return self.goal_bar

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
        rows = self.messages.model().rowCount() if hasattr(self.messages, "model") and self.messages.model() is not None else -1
        source = getattr(self.message_history, "page_source", None)
        pages = len(getattr(source, "pages", ())) if source is not None else -1
        print(
            f"QtThreadView {type(self).__name__} initial load done: "
            f"rows={rows} pages={pages} source={type(source).__name__ if source else None}",
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
