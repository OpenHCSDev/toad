"""Qt's post-bind mailbox view.

Replaces `QtOpeningSessionView` after `ThreadNavigation.bind` has supplied the
real thread identity + load plan. Mirrors the lifecycle `MainScreen` (Textual)
has after its `.use_mailbox()` + `prepared.bind(view)` land: the view carries
project + thread identity + the presentation's load plan, satisfies the
SessionScope / Qt-page surface, and renders the thread's transcript.

Transcript machinery (`QtHistoryWindow` + `TranscriptPresentation` +
`QtTranscriptHistory` and the rows under it) are inherited from
`QtThreadView` — the same shared base `QtAcpSessionView` uses so the two
thread-bound views share one implementation of the transcript stack, not
two. The mailbox-specific pieces (identity, `use_mailbox`, `apply_native_load_plan`,
NoAgent binding default) stay here.
"""

from __future__ import annotations

import asyncio

from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.acp.agent_session import UnopenedSessionDisposition
from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.client.observed_field import ObservedField
from toad.client.session_scope import BoundSources
from toad.qt.composer import MailboxComposer
from toad.qt.thread_view import QtThreadView
from toad.thread_identity import NoThreadIdentity, ThreadIdentity
from toad.transcript_scope import TranscriptScope
from toad.qt.metrics import UiGap


class QtMailboxView(QtThreadView, BoundSources):
    """Qt bound view for a thread opened through `thread_navigation.open`.

    Inherits `BoundSources` (a `SessionScope`) for its toolkit-neutral defaults (`bound_agent -> None`,
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

    # Class-level defaults satisfy `QtThreadView`'s abstract properties so this
    # class is instantiable; `__init__` assigns the real widgets.
    identity_line: ElidedLine = None  # type: ignore[assignment]
    thread_activity = None
    goal_bar = None

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
        # The shared transcript stack: `messages`, `transcript`, `message_history`.
        self._setup_transcript(app)
        self.identity_line = ElidedLine(f"Mailbox: {thread_incarnation.name}")
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app.renderer.themed(self.identity_line, lambda: self.identity_line.setStyleSheet(
            f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};"))
        info = QHBoxLayout()
        info.setContentsMargins(UiGap.loose, UiGap.normal, UiGap.loose, UiGap.normal)
        info.addWidget(self.identity_line, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(info)
        layout.addWidget(self.messages, 1)
        # Under the transcript, Textual's order: flash, sweep, status, goal, prompt.
        self._setup_prompt_stack(app, layout, thread_incarnation)

    def composer_class(self) -> type[MailboxComposer]:
        """Textual's `MailboxSessionSources.prompt`: a `MailboxPrompt`."""
        return MailboxComposer

    @property
    def composer_label(self) -> str:
        return self.thread_incarnation.name

    def present_thread_status(self) -> None:
        """A CLI thread shows Core's configuration answer, as Textual's
        `MailboxSessionSources.thread_presented` reads it."""
        asyncio.ensure_future(self.thread_scope.show_mailbox_status(self, self.app.coordination_access))

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
        `ThreadIdentity(owner, root)` that `thread_identity` then returns.

        The status rows bound at construction read `NoTranscript`; with the identity
        known, the status thread and Core's configuration answer are read for it."""
        self._identity = ThreadIdentity(owner, root)
        self.refresh_thread_status()
        self.present_thread_status()

    # ---- ThreadNavigation.bind hooks ----

    def use_mailbox(self) -> None:
        """`ThreadNavigation.bind(screen)` calls `screen.use_mailbox()`; Textual
        toggles MainScreen's content-mode here. Qt's mailbox view is permanently
        in mailbox mode; nothing to flip."""

    # ---- Content lifecycle ----

    async def _prepare_content(self) -> None:
        """`ThreadOpening.mount` awaits this after bind. The transcript's
        `_initial_page_source` built in `_setup_transcript` already reads from
        `self.transcript.get_transcript_page`; the live page restore drives
        through the pager without extra async work here."""

    # ---- SessionScope lifecycle ----

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

    def opening_failed(self, error: Exception) -> None:
        """If the opening path somehow fails AFTER the swap, surface the error
        on the identity line so the user sees why nothing loaded. Normally the
        opening placeholder absorbs this before the swap happens; this is
        defense in depth."""
        self.identity_line.setText(
            f"Mailbox {self.thread_incarnation.name} failed: {error}"
        )
        self.app.show_error(error, "Mailbox open failed")
