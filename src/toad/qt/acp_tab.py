"""The Qt phone's Claude-CLI session tab: shows a saved ACP session's transcript.

Textual's CLI-session view (``toad.screens.main.MainScreen`` + ``toad.widgets.conversation.Conversation``)
is a ~2k-line Screen that owns the agent binding, the composer, the transcript and a full
session presentation. The Qt phone starts with the read half: a saved transcript rendered
through the shared pager, Qt's row delegate and the Qt fragment flavors declared in
``toad.qt.history.QT_FRAGMENT_CLASSES``. Composing new prompts to the agent and the live
presentation machinery stay as next-fork work; the tab opens, the identity binds and the
transcript renders with tool-call + CLI-own-message fragments visible.

``QtNativeSessionEntry`` is the Qt counterpart of ``TextualNativeSessionEntry`` in
``toad.session_entry``: it shows ``SessionTabIdentity`` (``AcpTab`` + ``MailboxTab``) and
its ``session_view`` returns this widget. The existing Qt entry for ``CommsTab`` stays with
wire bus conversations in ``ConversationView``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.client.session_entry import NativeSessionEntry
from toad.client.session_scope import NoSessionOrigin, SessionOrigin
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.launch_binding import AgentBinding
from toad.qt.history import QT_FRAGMENT_CLASSES, QtConversationHistory, QtHistoryWindow
from toad.qt.window import Page, QtSessionEntry
from toad.thread_identity import NoThreadIdentity

if TYPE_CHECKING:
    from agent_comms.projects.checkouts import Checkout

    from toad.client.session_tracker import SessionDetails
    from toad.qt.window import QtToadApp


def _toad_app() -> QtToadApp:
    """The running Qt app widget. Looked up by type name so this module avoids a circular
    import with ``toad.qt.window`` at construction time; there is only ever one QtToadApp
    on the running process."""
    from PySide6.QtWidgets import QApplication

    from toad.qt.window import QtToadApp

    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QtToadApp):
            return widget
    raise RuntimeError("No QtToadApp window is running")


class QtAcpSessionView(Page, QWidget, metaclass=PyQtWidgetMeta):
    """A Qt Claude-CLI session tab.

    What this renders today: the bound session's identity line, and the transcript
    through Qt's existing history window using ``QT_FRAGMENT_CLASSES`` so tool-call,
    context, bus-message and sent-message fragments all appear as their Qt siblings.

    Not wired yet: the agent connection (sending new prompts), the full session
    presentation lifecycle, the composer, the thread sidebar. Opening the tab no longer
    crashes and reading an existing CLI session's transcript works end-to-end.
    """

    def __init__(
        self,
        app: QtToadApp,
        project: Checkout,
        binding: AgentBinding,
        session_pk: int,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.project = project
        self._agent_binding = binding
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._identity = binding.initial_identity(NoThreadIdentity())
        # NativeSessionEntry.__call__ writes these before mount.
        self.session_details: SessionDetails | None = None
        self._mode: str = f"acp:{session_pk}"
        # Transcript window + history reader; same classes as ConversationView uses.
        self.messages = QtHistoryWindow(app.renderer.scheme)
        self.message_history = QtConversationHistory(self.messages, self, app)
        # Layout: an identity line on top, the history below.
        self.identity_line = ElidedLine(f"ACP session #{session_pk}")
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.identity_line.setStyleSheet(f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};")
        info = QHBoxLayout()
        info.setContentsMargins(6, 4, 6, 4)
        info.addWidget(self.identity_line, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(info)
        layout.addWidget(self.messages, 1)
        # A placeholder for the composer row until the agent-send path lands.
        self.pending_composer = QLabel("Composing new prompts from the Qt client is coming next.")
        self.pending_composer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pending_composer.setStyleSheet(f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};")
        layout.addWidget(self.pending_composer)

    @property
    def mode(self) -> str:
        if self.session_details is not None:
            return self.session_details.identity.mode
        return self._mode

    @property
    def thread_identity(self):
        return self._identity

    @property
    def origin(self) -> SessionOrigin:
        # The real origin wires the agent binding and view; until that lands, the no-op
        # origin reports mode-only, which the sidebar + tab-order already handle.
        return NoSessionOrigin(self.mode)

    def shown(self, window, visited) -> None:  # type: ignore[override]
        """Selected: record the visit, let the history reload."""
        if self.session_details is not None:
            visited(self.session_details.identity)
        self.reload()

    def reload(self) -> None:
        """A transcript's source is live-bound by ``NativeSessionEntry.__call__``; if no
        source has been initialised, the history window just stays empty."""


class QtNativeSessionEntry(QtSessionEntry, NativeSessionEntry, shows=(SessionTabIdentity,)):
    """Qt entry for a Claude-CLI session tab (``AcpTab``, ``MailboxTab``). Keeps
    ``shows=(CommsTab,)`` separate so bus conversations continue to route through
    ``ConversationView`` and its ``WireSource`` wiring."""

    @staticmethod
    def session_view(
        project: Checkout,
        binding: AgentBinding,
        *,
        session_pk: int,
        initial_prompt: str | None = None,
    ) -> QtAcpSessionView:
        return QtAcpSessionView(_toad_app(), project, binding, session_pk, initial_prompt)


# Re-export CommsTab-shape so any importer that needs to disambiguate has one name.
__all__ = ("QtAcpSessionView", "QtNativeSessionEntry", "CommsTab")
