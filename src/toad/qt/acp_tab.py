"""The Qt phone's Claude-CLI session tab: shows a saved ACP session's transcript and takes
new prompts to its bound agent.

Textual's CLI-session view (``toad.screens.main.MainScreen`` + ``toad.widgets.conversation.Conversation``)
is a ~2k-line Screen that owns the agent binding, the composer, the transcript and a full
session presentation. The Qt phone ships the read half plus a working composer: a saved
transcript rendered through the shared pager, Qt's row delegate and the Qt fragment flavors
declared in ``toad.qt.history.QT_FRAGMENT_CLASSES``, and a ``Composer`` wired to publish
``UserInputSubmitted`` into Core's event stream the same way Textual's prompt does from
``widgets/conversation.py:901-904``. Any backend that is listening for the event picks it up
and submits through its own ``ConversationSubmissions`` family; if nothing is listening the
composer flashes a visible submitting status so the dead branch is loud, not silent.

The live-presentation lifecycle (agent reconnection, queue summary, receipt follow-through)
is a next-fork cut. What this tab gives is: typing a message in the Qt APK produces a
``UserInputSubmitted`` in Core with the same body shape Textual's prompt produces, and the
composer visibly reflects the pending send until the view's ``submissions_changed`` is
called by its ``BusSubmissions``.

``QtNativeSessionEntry`` is the Qt counterpart of ``TextualNativeSessionEntry`` in
``toad.session_entry``: it shows ``SessionTabIdentity`` (``AcpTab`` + ``MailboxTab``) and
its ``session_view`` returns this widget. The existing Qt entry for ``CommsTab`` stays with
wire bus conversations in ``ConversationView``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.session_entry import NativeSessionEntry
from toad.client.session_scope import NoSessionOrigin, SessionOrigin
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.core import input_events
from toad.launch_binding import AgentBinding
from toad.qt.composer import Composer, ComposerHost
from toad.qt.history import QT_FRAGMENT_CLASSES, QtConversationHistory, QtHistoryWindow
from toad.qt.window import Page, QtSessionEntry
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame
from toad.slash_command import SlashCommand
from toad.submission_queue import NoQueueSource, QueueSource
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


class QtAcpSessionView(ComposerHost, Page, WorkspaceHosted, QWidget, metaclass=PyQtWidgetMeta):
    """A Qt Claude-CLI session tab.

    What this renders today: the bound session's identity line, the transcript through Qt's
    existing history window using ``QT_FRAGMENT_CLASSES`` so tool-call, context, bus-message
    and sent-message fragments all appear as their Qt siblings, and a Qt ``Composer``
    (``Composer`` from ``toad.qt.composer`` — the same widget ``ConversationView`` uses for
    bus threads). ``submit`` publishes ``UserInputSubmitted`` into Core's event stream the
    way Textual's ``Prompt.send`` does at ``widgets/conversation.py:901-904``; a listening
    backend ``Conversation`` catches it through ``on_user_input_submitted`` and routes
    through its ``ConversationSubmissions`` family. The composer is also a ``ComposerHost``
    via ``MessageDestination`` so slash commands and @-mentions can fill in once
    ``update_slash_commands`` / ``set_mention_candidates`` are wired by the surrounding
    session lifecycle.

    Still waiting on the full ``widgets/conversation.Conversation`` lifecycle port
    (``agent_binding: var[AgentConnection]`` + ``OperationalSessionSources``): live
    reconnect, receipt notification follow (needs transcript-reload hook to call
    ``self.composer.receipt.follow`` the way ``ConversationView._refresh_source`` does
    at ``src/toad/qt/window.py:910``), real ``CommandCatalog.read`` slash commands and
    mention candidates (need ``agent.presentation.commands`` which only exists after
    ``agent_binding.start_session``), and a session-scoped thread sidebar pane. The
    global thread-sidebar placement (``ThreadSidebarPlacement`` on ``QtToadApp``) is
    already shared with every tab.
    """

    # Default until the live agent-session plumbing wires a ``NativeQueueSource``:
    # ``BusSubmissions.queue_evidence`` reads ``self.view.queue_source`` and would
    # AttributeError on the composer's first ``show_submitting`` without this. Same
    # pattern ``ConversationView`` and Textual's ``CommsChatView`` use
    # (``src/toad/qt/window.py:749``, ``src/toad/widgets/comms_chat.py:68``).
    queue_source: QueueSource = NoQueueSource()

    @property
    def screen(self) -> WorkspaceFrame:
        return self.window()

    def __init__(
        self,
        app: QtToadApp,
        project: Checkout,
        binding: AgentBinding,
        session_pk: int,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()
        # ``QtToadApp`` subclasses ``ClientApplication``, so its ``.app`` attribute satisfies
        # ``ComposerHost.app: ClientApplication`` directly and gives the Composer access to
        # the theme, renderer and Core event stream.
        self.app = app
        self.project = project
        self._agent_binding = binding
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._identity = binding.initial_identity(NoThreadIdentity())
        # ``NativeSessionEntry.__call__`` writes these before mount.
        self.session_details: SessionDetails | None = None
        self._mode: str = f"acp:{session_pk}"
        # Bus-submissions owner: the Composer reads ``queue_summary`` + ``delivering`` off
        # it, and on each send ``self`` publishes the event the backend converts into a
        # real submission. A queue-renderer hook will plug into this later.
        self.submissions = BusSubmissions(self)
        # Transcript window + history reader; same classes as ConversationView uses.
        self.messages = QtHistoryWindow(app.renderer.scheme)
        self.message_history = QtConversationHistory(self.messages, self, app)
        # Layout: an identity line on top, the history below, the composer at the bottom.
        self.identity_line = ElidedLine(f"ACP session #{session_pk}")
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.identity_line.setStyleSheet(f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};")
        info = QHBoxLayout()
        info.setContentsMargins(6, 4, 6, 4)
        info.addWidget(self.identity_line, 1)
        # Composer: the same shape ``ConversationView`` uses for bus DMs, pointed at this
        # host so ``submit`` ends up calling ``self.submit`` with the typed text.
        self.composer = Composer(self, app.renderer, "Send to agent")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(info)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.composer)

    # ---- ComposerHost contract ----
    #
    # ``ComposerHost`` from ``toad.qt.composer`` names ``app`` (satisfied above),
    # ``submissions`` (satisfied above) and ``submit``. ``ConversationCommands`` (the base of
    # ``ComposerHost``) names ``update_slash_commands`` which the composer calls when the
    # user types a ``/``; until the session lifecycle wires the real command catalog, we
    # hand the composer an empty list so the slash offers row stays hidden rather than
    # throwing.

    def update_slash_commands(self) -> None:
        """Called by the composer when the user starts typing a slash command. The session
        lifecycle will replace this with the real ``CommandCatalog`` pull."""
        self.composer.set_commands([])

    def submit(self, text: TypedText) -> None:
        """Publish ``UserInputSubmitted`` through Core's event stream — the same payload
        Textual's prompt publishes at ``widgets/conversation.py:901-904``. A listening
        backend ``Conversation`` picks it up and routes through its ``ConversationSubmissions``
        family. If no backend is listening, the submit silently vanishes; the composer
        reflects that visibly through its ``show_submitting`` state until the queue reader
        catches up. Shell-prefix detection matches ``conversation.py:900``."""
        body = text.text
        event = input_events.UserInputSubmitted(
            body[1:] if body.startswith("!") else body,
            shell=body.startswith("!"),
        )
        try:
            self.app.events.publish(event)
        except Exception as error:
            self.composer.show_failure(f"Send failed: {error}")
            self.composer.restore_draft(body)
            return
        self.composer.show_submitting()

    def submissions_changed(self) -> None:
        """``BusSubmissions.publish_pending`` calls this when the queue changes."""
        self.composer.show_submitting()

    def notification_targets(self):
        """The Composer's ``Receipt`` subscribes against the view's notification targets.
        Nothing to subscribe on until the backend receipt plumbing lands."""
        return ()

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
