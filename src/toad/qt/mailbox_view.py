"""Qt's post-bind mailbox view.

Replaces `QtOpeningSessionView` after `ThreadNavigation.bind` has supplied the real
thread identity + load plan. Mirrors the lifecycle `MainScreen` (Textual) has
after its `.use_mailbox()` + `prepared.bind(view)` land: the view carries project
+ thread identity + the presentation's load plan, satisfies the SessionScope /
Qt-page surface, and renders the thread.

Initial PR scope is the LIFECYCLE SWAP — proving that a Qt row tap actually
transitions from the opening placeholder into a bound view, not that this view
renders the full transcript yet. Future PRs enrich the body (QtTranscriptHistory
over the load_plan's transcript scope, Composer, etc.) by extending this class.
Today the body is a label that confirms the bind happened; before this class the
user saw "Opening …" forever because the opening placeholder was never replaced.
"""

from __future__ import annotations

from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.message_category import all_categories
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.acp.agent_session import UnopenedSessionDisposition
from toad.client.session_scope import SessionScope
from toad.thread_identity import ThreadIdentity


class _MailboxPresentation:
    """Same shape `ThreadNavigation.bind` writes to on Textual's MainScreen
    (`screen.presentation.sources.load_plan = plan`). Qt doesn't yet have a
    real `TranscriptPresentation` wired through mailbox-view rendering; the
    bind landing site is kept so `ThreadNavigation.bind` subclasses that set
    `sources` / `load_plan` run cleanly, and future PRs can replace this with
    the real presentation driving the transcript history."""

    class _Sources:
        def __init__(self) -> None:
            self.load_plan = None

    def __init__(self) -> None:
        self.sources = _MailboxPresentation._Sources()


class QtMailboxView(SessionScope, QWidget):
    """Qt bound view for a thread opened through `thread_navigation.open`.

    Constructed from the `ThreadOpening`'s request/origin/prepared tuple by
    `QtToadApp.replace_opening_view`. The opening placeholder is swapped out
    of `QtWorkspaceViews.pages` and this view takes its mode slot, so
    `prepared.bind(view)` + `session_navigation.bind_opened(view, ...)` +
    `view._prepare_content()` + `view.wait_content_ready()` all run against
    the bound-state view rather than the opening placeholder.
    """

    def __init__(self, app, project: Checkout, thread_incarnation: ThreadIncarnation, root: str) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Widget)
        self.app = app
        self.project = project
        self.thread_incarnation = thread_incarnation
        self.root = root
        # `QtWorkspaceViews.swap_page` copies the opening view's mode across, so
        # workspace lookups stay consistent through the swap; keep an empty default
        # until the swap sets it.
        self.id = ""
        # `session_navigation.bind_opened` writes `self.session_details =` via
        # `NativeSessionEntry.__call__`; left None here because the swap bypasses
        # the factory and is set directly in `replace_opening_view`.
        self.session_details = None
        # The thread identity gets its real value from `bind_thread` below; the
        # default here is NoThreadIdentity (SessionScope default) until bind lands.
        self._identity: object | None = None
        # `QtCategoryFilter.present` reads `view.visible_categories`; mirrors the
        # initial state `ConversationView.__init__` sets at `window.py:1061`.
        self.visible_categories = all_categories()
        # Matches Textual's MainScreen: `prepared.bind` lands on
        # `view.presentation.sources.load_plan`.
        self.presentation = _MailboxPresentation()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self._label = QLabel(f"Mailbox: {thread_incarnation.name}", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)

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
    def thread_identity(self) -> object:
        """Returns the bound ThreadIdentity once `bind_thread` has been called;
        before that, falls through to SessionScope's NoThreadIdentity default.
        Mirrors `MainScreen.bind_thread`'s `self._identity = ThreadIdentity(owner, root)`
        pattern at `screens/main.py:386`."""
        if self._identity is not None:
            return self._identity
        return super().thread_identity

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

    # ---- Content lifecycle ----

    async def _prepare_content(self) -> None:
        """`ThreadOpening.mount` awaits this after bind. Textual's MainScreen
        drives presentation / content preparation; this placeholder is already
        drawn at construction, so nothing async to prepare today. Future PRs
        wire `QtTranscriptHistory` over the load plan here."""

    async def wait_content_ready(self) -> None:
        """Placeholder content is always ready. Future transcript rendering
        would await its initial page here."""

    # ---- SessionScope lifecycle no-ops (placeholder has no Core subscriptions
    #      or transcript history yet; future PRs that add them will override) ----

    def close_core_events(self) -> None: ...
    async def retire_presentation(self) -> None: ...
    def belongs_to_wire(self, root) -> bool:
        return self.root == str(root)

    # ---- Qt page lifecycle (shown/reload) ----

    def shown(self, window, visited) -> None:
        """`QtWorkspaceViews.select` calls `page.shown(app, visited)` when this
        page becomes the current widget. No visit-identity to record yet; future
        PRs wiring the session tracker call that here."""

    def reload(self) -> None:
        """`QtToadApp.stores_changed` calls `selected.reload()` on every revision
        tick. Placeholder has no content to reload; future transcript body will."""

    def opening_failed(self, error: Exception) -> None:
        """If the opening path somehow fails AFTER the swap, repaint the label so
        the user sees it. Normally the opening placeholder absorbs this before the
        swap happens; this is defense in depth."""
        self._label.setText(f"Mailbox {self.thread_incarnation.name} failed:\n{error}")
