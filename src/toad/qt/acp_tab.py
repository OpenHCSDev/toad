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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.agent_binding import AgentConnection
from toad.client.bus_submission import TypedText
from toad.client.session_entry import NativeSessionEntry
from toad.client.session_scope import NoSessionOrigin, SessionOrigin
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.transcript_scope import TranscriptScope

from toad.launch_binding import AgentBinding
from toad.qt.composer import ProjectComposer
from toad.qt.thread_view import QtThreadView
from toad.qt.window import QtSessionEntry
from toad.slash_command import SlashCommand

from toad.thread_identity import NoThreadIdentity
from toad.qt.metrics import UiGap

if TYPE_CHECKING:
    from agent_comms.projects.checkouts import Checkout

    from toad.agent import AgentBase
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


class QtAcpSessionView(
    QtThreadView,
    metaclass=PyQtWidgetMeta,
):
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

    # Class-level defaults satisfy `QtThreadView`'s abstract properties so this
    # class is instantiable; `_setup_prompt_stack` assigns the real widgets.
    identity_line: ElidedLine = None  # type: ignore[assignment]
    thread_activity = None
    goal_bar = None

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
        # Shared transcript stack: QtHistoryWindow + TranscriptPresentation +
        # QtTranscriptHistory + QtAgentActivity, plus the ThreadBindingDispatch state
        # and session_details slot. Lives on `QtThreadView`; same base `QtMailboxView`
        # uses, so neither view carries a parallel copy. See `QtThreadView._setup_transcript`.
        self._setup_transcript(app)
        # Layout: an identity line on top, the history below, the composer at the bottom.
        self.identity_line = ElidedLine(f"ACP session #{session_pk}")
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
        # Under the transcript, Textual's order: flash, sweep, status, goal, prompt. A
        # binding with no `ThreadIncarnation` has no goal owner, so no goal bar.
        self._composer_label = "agent"
        incarnation = self._agent_binding.initial_identity(NoThreadIdentity()).optional_thread_incarnation()
        self._setup_prompt_stack(app, layout, incarnation)
        # Live reconnect hook: when the agent-binding changes (first attach or a real
        # reconnect), re-project state via ``apply_bound_agent`` and show the connected
        # notice once the new agent is ready. Textual's ``watch_agent_binding`` does the
        # same work through its reactive system; here it's an ``ObservedField`` watcher.
        self.on_agent_binding_change(self._on_agent_binding_change)

    # ---- AgentBoundConversation hooks ----

    def _on_agent_binding_change(
        self, _before: "AgentConnection", after: "AgentConnection"
    ) -> None:
        if after.ready:
            self.apply_bound_agent(after)  # type: ignore[arg-type]
            self.agent_connected(after)  # type: ignore[arg-type]

    def apply_bound_agent(self, agent: AgentBase) -> None:
        """As Textual's `Conversation.apply_bound_agent`: the status thread and working
        answer, the agent's name on the identity line and composer, and its context
        measurement as the info bar's status."""
        super().apply_bound_agent(agent)
        info = agent.get_info()
        self.identity_line.setText(f"ACP session #{self._session_pk} · {info}")
        self._composer_label = info
        if self.composer is not None:
            self.composer.labelled(info)
        self.thread_status = agent.context_measurement.status()

    def agent_connected(self, agent: AgentBase) -> None:
        """Flash the connected notice, as Textual's `Conversation.agent_connected`."""
        self.flash_success(f"{agent.get_info()} connected")
        self.app.usage.publish("agent-session-begin")

    def composer_class(self) -> type[ProjectComposer]:
        """Textual's `OperationalSessionSources.prompt`: the operational prompt."""
        return ProjectComposer

    @property
    def composer_label(self) -> str:
        return self._composer_label

    @property
    def mode(self) -> str:
        """Session mode is owned by the session identity when a SessionDetails has been
        set; before that, derive the fallback mode from the session pk — never cache it."""
        if self.session_details is not None:
            return self.session_details.identity.mode
        return f"acp:{self._session_pk}"

    @property
    def thread_identity(self):
        """Read the binding's current initial identity fresh each access — a cached
        `_identity` captured at __init__ goes stale if the binding is later re-bound
        to a different identity (apply_bound_agent updates the visible labels but
        a cache here would not update)."""
        return self._agent_binding.initial_identity(NoThreadIdentity())

    @property
    def origin(self) -> SessionOrigin:
        # The real origin wires the agent binding and view; until that lands, the no-op
        # origin reports mode-only, which the sidebar + tab-order already handle.
        return NoSessionOrigin(self.mode)

    def transcript_scope(self) -> TranscriptScope:
        """The transcript scope this view is bound to — the one `BoundView.thread_scope`
        reads on bind to wire `thread_observed` into Core's observation. Textual's
        `Conversation.transcript_scope` goes through `query_ancestor(SessionScope).origin.
        transcript_scope()`; on Qt the identity owns the scope directly, so this is a
        straight delegation."""
        return self.thread_identity.transcript_scope()

    # is_attached, is_leaving, is_current_session, thread_presented live on `QtThreadView`.

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
