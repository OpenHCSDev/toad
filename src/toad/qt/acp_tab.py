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
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming import StatusColorRole
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.agent_binding import AgentConnection
from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.session_entry import NativeSessionEntry
from toad.client.session_scope import NoSessionOrigin, SessionOrigin
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.transcript_scope import TranscriptScope
from toad.core import input_events
from toad.launch_binding import AgentBinding
from toad.qt.composer import Composer, ComposerHost
from toad.qt.thread_view import QtThreadView
from toad.qt.window import QtSessionEntry
from toad.slash_command import SlashCommand
from toad.submission_queue import NoQueueSource, QueueSource
from toad.thread_identity import NoThreadIdentity

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
    ComposerHost,
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

    # Default until the live agent-session plumbing wires a ``NativeQueueSource``:
    # ``BusSubmissions.queue_evidence`` reads ``self.view.queue_source`` and would
    # AttributeError on the composer's first ``show_submitting`` without this. Same
    # pattern ``ConversationView`` and Textual's ``CommsChatView`` use
    # (``src/toad/qt/window.py:749``, ``src/toad/widgets/comms_chat.py:68``).
    queue_source: QueueSource = NoQueueSource()

    # `agent_binding` lives on `QtThreadView` now — the same descriptor QtMailboxView
    # also inherits, so there's one owner for the field both Qt views write to. See
    # `QtThreadView.agent_binding`.

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
        # Bus-submissions owner: the Composer reads ``queue_summary`` + ``delivering`` off
        # it, and on each send ``self`` publishes the event the backend converts into a
        # real submission. A queue-renderer hook will plug into this later.
        self.submissions = BusSubmissions(self)
        # Layout: an identity line on top, the history below, the composer at the bottom.
        self.identity_line = ElidedLine(f"ACP session #{session_pk}")
        self.identity_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.identity_line.setStyleSheet(f"color: {ForegroundColour.rgb(app.renderer.scheme).hex};")
        info = QHBoxLayout()
        info.setContentsMargins(6, 4, 6, 4)
        info.addWidget(self.identity_line, 1)
        # Composer: the same shape ``ConversationView`` uses for bus DMs, pointed at this
        # host so ``submit`` ends up calling ``self.submit`` with the typed text. On
        # Android, mounting ``ComposerEditor`` (QPlainTextEdit) during ``__init__`` races
        # ``QtAndroidAccessibility::runInObjectContext()`` with Qt's first-paint EGL
        # setup, deadlocking the window (upstream Qt-for-Android bug). Mount it one tick
        # later so first paint lands first; the composer reparents cleanly into the
        # layout slot reserved for it.
        self.composer: Composer | None = None
        self._pending_composer_label: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(info)
        layout.addWidget(self.agent_activity)
        layout.addWidget(self.messages, 1)
        self._composer_layout = layout
        QTimer.singleShot(0, lambda: self._mount_composer(app))
        # Bind the transcript once the message_history child exists: `BoundView` reads
        # `self.transcript_history` immediately. Textual binds in its `on_mount`
        # (`widgets/conversation.py:1766`); on Qt the equivalent moment is right after
        # the `message_history` attribute is assigned, before any agent attaches.
        self.transcript.bind(self)
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

    def _mount_composer(self, app) -> None:
        """Mount the Composer one event-loop tick after construction. See the docstring in
        ``__init__``: on Qt-for-Android the ``QPlainTextEdit`` inside ``Composer`` races
        ``QtAndroidAccessibility::runInObjectContext()`` with the first-paint EGL setup,
        deadlocking the window. Deferring by one tick lets the main-window paint land
        first; the composer attaches cleanly after and Android's a11y probe sees it only
        once the EGL surface is already current.
        """
        self.composer = Composer(self, app.renderer, "Send to agent")
        self._composer_layout.addWidget(self.composer)
        if self._pending_composer_label is not None:
            self.composer.labelled(self._pending_composer_label)
            self._pending_composer_label = None

    def apply_bound_agent(self, agent: AgentBase) -> None:
        """Mirror the agent's current identity on the composer and the identity line.

        Textual's ``Conversation.apply_bound_agent`` also updates its thread-status pill
        and re-arms the goal + delivery observations; those run through
        ``QtGoalBar``/``observed thread status`` on Qt, which are driven by Core events
        and don't need a direct call from here.
        """
        info = agent.get_info()
        self.identity_line.setText(f"ACP session #{self._session_pk} · {info}")
        label = f"Send to {info}"
        if self.composer is None:
            self._pending_composer_label = label
        else:
            self.composer.labelled(label)

    def agent_connected(self, agent: AgentBase) -> None:
        """Flash the connected notice on the status line; usage milestone through the app."""
        self.app.status_line.show_status(f"{agent.get_info()} connected", StatusColorRole.INFO)
        self.app.usage.publish("agent-session-begin")

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
        if self.composer is None:
            return
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

    def notification_targets(self):
        """The Composer's ``Receipt`` subscribes against the view's notification targets.
        Nothing to subscribe on until the backend receipt plumbing lands."""
        return ()

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
