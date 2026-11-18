"""Qt's post-bind mailbox view.

Replaces `QtOpeningSessionView` after `ThreadNavigation.bind` has supplied the
real thread identity + load plan. Mirrors the lifecycle `MainScreen` (Textual)
has after its `.use_mailbox()` + `prepared.bind(view)` land: the view carries
project + thread identity + the presentation's load plan, satisfies the
SessionScope / Qt-page surface, and renders the thread's transcript.

Transcript machinery (`QtHistoryWindow` + `TranscriptPresentation` +
`QtTranscriptHistory` + `QtAgentActivity`) is inherited from
`QtThreadView` — the same shared base `QtAcpSessionView` uses so the two
thread-bound views share one implementation of the transcript stack, not
two. The mailbox-specific pieces (identity, `use_mailbox`, `apply_native_load_plan`,
NoAgent binding default) stay here.
"""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from pyqt_reactive.theming import StatusColorRole
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.acp.agent_session import UnopenedSessionDisposition
from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.observed_field import ObservedField
from toad.client.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.qt.thread_view import QtThreadView
from toad.thread_identity import NoThreadIdentity, ThreadIdentity
from toad.transcript_scope import TranscriptScope
from toad.qt.metrics import UiGap


class _MailboxPresentation:
    """Same shape `ThreadNavigation.bind` writes to on Textual's MainScreen
    (`screen.presentation.sources.load_plan = plan`). Kept so
    `ExternalThreadNavigation` / `NativeThreadNavigation` subclasses that assign
    to `screen.presentation.sources` run cleanly without a special case."""

    class _Sources:
        def __init__(self) -> None:
            self.load_plan = None

    def __init__(self) -> None:
        self.sources = _MailboxPresentation._Sources()


class QtMailboxView(QtThreadView, SessionScope):
    """Qt bound view for a thread opened through `thread_navigation.open`.

    Inherits `SessionScope` for its toolkit-neutral defaults (`bound_agent -> None`,
    `thread_identity -> NoThreadIdentity`, etc.) — `QtThreadView` itself does not
    carry SessionScope because `QtAcpSessionView` provides those defaults through
    `ObservedAgentBinding` instead; both arrangements leave the view with a usable
    `bound_agent` / `thread_identity` / etc. that generic sidebar panels
    (`QtPlan.bind`, `QtCategoryFilter.present`) read.

    Constructed from the `ThreadOpening`'s request/origin/prepared tuple by
    `QtToadApp.replace_opening_view`. The opening placeholder is swapped out
    of `QtWorkspaceViews.pages` and this view takes its mode slot, so
    `prepared.bind(view)` + `session_navigation.bind_opened(view, ...)` +
    `view._prepare_content()` + `view.wait_content_ready()` all run against
    the bound-state view rather than the opening placeholder.

    Shares the transcript stack with `QtAcpSessionView` through `QtThreadView`.
    """

    # `agent_binding` lives on `QtThreadView` (shared owner, PR #...) — a NoAgentConnection
    # ObservedField by default. Mailbox view inherits it without re-declaring; the
    # field exists if a later PR wires a real binding here (e.g. an opened mailbox
    # that upgrades to a live session).

    # Class-level defaults satisfy `QtThreadView`'s abstract properties so this
    # class is instantiable; `__init__` assigns the real widgets.
    identity_line: ElidedLine = None  # type: ignore[assignment]
    composer: "Composer | None" = None
    submissions: "BusSubmissions" = None  # type: ignore[assignment]
    thinking_line: "QWidget" = None  # type: ignore[assignment]
    thread_status_line: "QWidget" = None  # type: ignore[assignment]

    def __init__(self, app, project: Checkout, thread_incarnation: ThreadIncarnation, root: str) -> None:
        super().__init__()
        # The app first: changing the window flags hides the widget, and the hide answers
        # through `QtHistoryNotifications.hideEvent`, which reads it.
        self.app = app
        self.setWindowFlags(Qt.WindowType.Widget)
        self.project = project
        self.thread_incarnation = thread_incarnation
        self.root = root
        # `QtWorkspaceViews.swap_page` copies the opening view's mode across so
        # workspace lookups stay consistent through the swap; keep an empty default
        # until the swap sets it.
        self.id = ""
        # `bind_thread` replaces this with the real ThreadIdentity.
        self._identity: ThreadIdentity | NoThreadIdentity = NoThreadIdentity()
        # Matches Textual's MainScreen: `prepared.bind` lands on
        # `view.presentation.sources.load_plan` via `apply_native_load_plan`.
        self.presentation = _MailboxPresentation()
        # Build the shared transcript stack (QtHistoryWindow + TranscriptPresentation
        # + QtTranscriptHistory + QtAgentActivity). After this call, `self.messages`,
        # `self.transcript`, `self.message_history`, `self.agent_activity` all exist.
        self._setup_transcript(app)
        # Identity line + layout — messages are the main body, activity ribbon above.
        self.identity_line = ElidedLine(f"Mailbox: {thread_incarnation.name}")
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.identity_line.setStyleSheet(f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};")
        info = QHBoxLayout()
        info.setContentsMargins(UiGap.loose, UiGap.normal, UiGap.loose, UiGap.normal)
        info.addWidget(self.identity_line, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(info)
        layout.addWidget(self.agent_activity)
        layout.addWidget(self.messages, 1)
        # Goal strip above the composer slot, matching ACP + Textual's `Conversation`
        # where `GoalBar` sits over its prompt. The bar hides itself when no goal
        # is set.
        goal_bar = self._mount_goal_bar(app, thread_incarnation)
        if goal_bar is not None:
            layout.addWidget(goal_bar)
        # Composer at the bottom. Hoisted on `QtThreadView` — same input path
        # ACP uses. Label targets the mailbox thread so the placeholder shows
        # the user where they're about to post.
        self._setup_composer(app, layout, f"Send to {thread_incarnation.name}")

    # ---- SessionScope identity ----

    @property
    def mode(self) -> str:
        return self.id

    @property
    def session_disposition(self):
        """`session_entry.thread_row` reads this via `source.session_disposition`;
        on Textual `MainScreen.session_disposition` returns
        `self.presentation.operational_binding.session_disposition`. Without a
        bound operational binding yet, mirror `AgentBinding`'s placeholder
        (`UnopenedSessionDisposition`) so row presentation runs cleanly."""
        return UnopenedSessionDisposition()

    @property
    def thread_identity(self) -> ThreadIdentity | NoThreadIdentity:
        """`NoThreadIdentity` until `bind_thread` sets the real one, as
        `MainScreen.bind_thread` does at `screens/main.py:386`."""
        return self._identity

    @property
    def origin(self) -> SessionOrigin:
        """Mailbox view has no live agent binding of its own; sidebar + tab-order
        already handle a no-op origin by mode. Mirrors `QtAcpSessionView.origin`
        at `qt/acp_tab.py:380`."""
        return NoSessionOrigin(self.mode)

    def transcript_scope(self) -> TranscriptScope:
        """The transcript scope this view is bound to — the one `BoundView.thread_scope`
        reads on bind to wire `thread_observed` into Core's observation."""
        return self.thread_identity.transcript_scope()

    # ---- session_navigation.bind_opened hooks ----

    def bind_project(self, project: Checkout) -> None:
        """`session_navigation.bind_opened` calls `view.bind_project(project)`;
        mirrors `MainScreen.bind_project` at `screens/main.py:520`."""
        self.project = project

    def bind_thread(self, owner, root: str) -> None:
        """`session_navigation.bind_opened` calls `view.bind_thread(owner, root)`;
        mirrors `MainScreen.bind_thread` at `screens/main.py:386`, builds the
        `ThreadIdentity(owner, root)` that `thread_identity` then returns."""
        self._identity = ThreadIdentity(owner, root)

    # ---- ThreadNavigation.bind hooks ----

    def use_mailbox(self) -> None:
        """`ThreadNavigation.bind(screen)` calls `screen.use_mailbox()`; Textual
        toggles MainScreen's content-mode here. Qt's mailbox view is permanently
        in mailbox mode; nothing to flip."""

    def apply_native_load_plan(self, plan) -> None:
        """`NativeThreadNavigation.bind(screen)` calls `screen.apply_native_load_plan(plan)`.
        Textual assigns `self.presentation.sources.load_plan = plan` which feeds the
        resumable-session restore. Qt keeps the same assignment shape so Core's
        bind logic reads the plan on the view's presentation surface."""
        self.presentation.sources.load_plan = plan

    def apply_external_mailbox_sources(self) -> None:
        """`ExternalThreadNavigation.bind(screen)` calls
        `screen.apply_external_mailbox_sources()`. Textual swaps in
        `MailboxSessionSources` which drags in the Textual-widget pyramid. The
        default SessionScope no-op already handles it; keep this override explicit
        so a future Qt-side mailbox-sources class has an obvious hook point."""

    # ---- Content lifecycle ----

    async def _prepare_content(self) -> None:
        """`ThreadOpening.mount` awaits this after bind. The transcript's
        `_initial_page_source` built in `_setup_transcript` already reads from
        `self.transcript.get_transcript_page`; the live page restore drives
        through the pager without extra async work here."""

    async def wait_content_ready(self) -> None:
        """Wait for the message_history's first page to be ready, so the user
        sees transcript content (not just an empty window) when the tab opens.
        Textual's MainScreen awaits its presentation's `content_ready` in the
        same shape."""
        if hasattr(self.message_history, "wait_content_ready"):
            await self.message_history.wait_content_ready()

    # ---- SessionScope lifecycle ----

    def close_core_events(self) -> None:
        """Release the thread-observation context so the bound view's Core
        subscription stops before the tab entry is forgotten. Mirrors the
        teardown `TranscriptPresentation._unbind_view` does at
        `transcript_publication.py:1026` — `ResourceRelease.close()` is the
        `ExitStack` API."""
        self._thread_observation.close()

    async def retire_presentation(self) -> None:
        """Let go of the drawn transcript before the tab it returns to is
        shown. `message_history.retire` (if present) tears down the presentation
        chain; otherwise there's nothing to let go of yet."""
        retire = getattr(self.message_history, "retire", None)
        if retire is not None:
            await retire()

    def belongs_to_wire(self, root) -> bool:
        return self.root == str(root)

    # ---- Qt page lifecycle ----

    def shown(self, window, visited) -> None:
        """`QtWorkspaceViews.select` calls `page.shown(app, visited)` when this
        page becomes the current widget. Record the visit if the session tracker
        has registered an identity yet; mirrors `QtAcpSessionView.shown`."""
        if self.session_details is not None:
            visited(self.session_details.identity)
        self.reload()

    def reload(self) -> None:
        """`QtToadApp.stores_changed` calls `selected.reload()` on every revision
        tick. The message_history re-reads through its pager on the next tick;
        no extra work needed here today."""

    def opening_failed(self, error: Exception) -> None:
        """If the opening path somehow fails AFTER the swap, surface the error
        on the identity line so the user sees why nothing loaded. Normally the
        opening placeholder absorbs this before the swap happens; this is
        defense in depth."""
        self.identity_line.setText(
            f"Mailbox {self.thread_incarnation.name} failed: {error}"
        )
        self.app.status_line.show_status(
            f"Mailbox open failed: {error}", StatusColorRole.ERROR
        )
