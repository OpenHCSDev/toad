"""Qt's agent session tab: Textual's `MainScreen` + `Conversation` for one ACP session.

The tab is an `AgentConversation`: when it is first shown, its launch attaches to it
(`AgentBinding.attach_to`), and an attached agent starts through the chain every frontend
inherits — the unbound view's sources create the agent (`SessionSources.create_agent`), the
agent attaches this view's surface (`agent_surface`), and its turn arrives through the shared
handlers (`AgentTurnEvents`) as live rows. A saved session reopens its agent's session; a
platform that cannot spawn agent processes never attaches one (`AgentProcesses`).

``QtNativeSessionEntry`` is the Qt counterpart of ``TextualNativeSessionEntry``: it shows
``SessionTabIdentity`` (``AcpTab`` + ``MailboxTab``) and builds this view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_comms.nominal.field_codec import NoAcpSessionId
from metaclass_registry.mro_dispatch import handles
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from ui_theme.scheme import ForegroundColour

from toad.agent_binding import AgentConnection
from toad.client.session_entry import NativeSessionEntry
from toad.client.session_scope import NoSessionOrigin, SessionOrigin
from toad.client.tab_identity import SessionTabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.core import events as core_events
from toad.core.input_events import UserInputSubmitted
from toad.launch_binding import AgentBinding, AgentConversation, AgentOrigin
from toad.qt.composer import ProjectComposer
from toad.qt.metrics import UiGap
from toad.qt.thread_view import QtThreadView
from toad.qt.window import QtSessionEntry
from toad.session_titles import FirstPromptTitle, SessionTitles
from toad.thread_identity import NoThreadIdentity
from toad.transcript_scope import TranscriptScope

if TYPE_CHECKING:
    from agent_comms.projects.checkouts import Checkout

    from toad.agent import AgentBase
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
    AgentConversation,
    AgentOrigin,
    SessionTitles,
    FirstPromptTitle,
    metaclass=PyQtWidgetMeta,
):
    """One agent session's tab: its identity line, the transcript through Qt's history
    window, the agent's live turn as rows, and the operational composer."""

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
        self.project_path = project
        self.launch = binding
        self._agent_session_id = NoAcpSessionId()
        self._session_pk = session_pk
        self._initial_prompt = initial_prompt
        self._native_agent_started_here = False
        self._attached = False
        # As Textual's Conversation: a session with no saved agent session guesses its title
        # from its first prompt (`FirstPromptTitle`; a resumed one keeps the saved name).
        self._auto_title_eligible = True
        self._setup_transcript(app)
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
        self._composer_label = binding.selected_agent("agent", lambda agent: agent.name)
        incarnation = binding.initial_identity(NoThreadIdentity()).optional_thread_incarnation()
        self._setup_prompt_stack(app, layout, incarnation)
        self.on_agent_binding_change(self._on_agent_binding_change)

    # ---- AgentOrigin: what the launch reads of the session it attaches to ----

    @property
    def is_current(self) -> bool:
        return self.is_current_session

    # ---- AgentConversation: the launch's agent starts here ----

    def defer_agent_start(self) -> None:
        """Start the attached agent once Qt has shown the tab (Textual waits for the
        presented frame the same way)."""
        QTimer.singleShot(0, self._start_agent)

    def present_without_agent(self) -> None:
        self.show_agent_info(self.operational_sources.agent_info(self))
        self.session_ready()

    def show_agent_info(self, text: str) -> None:
        """The identity line and composer name the agent, as Textual's info bar does."""
        self.identity_line.setText(f"ACP session #{self._session_pk} · {text}")
        self._composer_label = text
        if self.composer is not None:
            self.composer.labelled(text)

    @property
    def agent_title(self) -> str:
        """The session's display name, as Textual's `Conversation.agent_title` reads its
        scope's: the tab's name once it has one, else the agent's."""
        if self.session_details is not None and self.session_details.name.display:
            return self.session_details.name.display
        return self.launch.selected_agent("agent", lambda agent: agent.name)

    def session_ready(self) -> None:
        """The agent can take input: its welcome shows once, then the launch's first
        prompt is sent (Textual's `Conversation.session_ready`)."""
        if self._native_agent_started_here:
            self._native_agent_started_here = False
            welcome = self.launch.selected_agent(None, lambda agent: agent.welcome)
            if welcome:
                self.run_worker(lambda: self.present_help_note(welcome), group="welcome")
        if self.agent_binding.configuration.model.requires_selection:
            self.flash("Choose a model to start")
            return
        prompt, self._initial_prompt = self._initial_prompt, None
        if prompt:
            event = UserInputSubmitted(prompt, shell=False)
            self.run_worker(lambda: self.submissions.submit(event), group="submit", exclusive=False)

    # ---- The bound agent ----

    @property
    def named_session(self):
        """`SessionTitles`: this tab names its session once the tracker gave it one."""
        return self.session_details

    def _on_agent_binding_change(
        self, _before: AgentConnection, after: AgentConnection
    ) -> None:
        if after.ready:
            self.apply_bound_agent(after)  # type: ignore[arg-type]

    @handles(core_events.AgentReady)
    async def on_agent_ready(self, event: core_events.AgentReady, message) -> None:
        """As Textual's `Conversation.on_agent_ready`: a first connect announces the agent;
        every ready re-reads its state and thread, and takes input."""
        if not event.reconnected:
            self.agent_binding.connected(self)
        self.apply_bound_agent(self.agent_binding)  # type: ignore[arg-type]
        self.session_ready()
        self.arm_thread_read()
        self.refresh_thread_status()

    def apply_bound_agent(self, agent: AgentBase) -> None:
        """As Textual's `Conversation.apply_bound_agent`: the status thread and working
        answer, the agent's name on the identity line and composer, and its context
        measurement as the info bar's status."""
        super().apply_bound_agent(agent)
        self.show_agent_info(agent.get_info())
        self.thread_status = agent.context_measurement.status()

    def agent_connected(self, agent: AgentBase) -> None:
        """Flash the connected notice, as Textual's `Conversation.agent_connected`. Qt sends
        no usage report: that delivery is the terminal app's (it reports the terminal program
        and size, and loads httpx)."""
        self.flash_success(f"{agent.get_info()} connected")

    async def agent_turn_over(self, stop_reason) -> None:
        """The turn ended: its live output settles and the next turn starts on a fresh
        block; a stop reason with a note says why."""
        self.turns.finish_client()
        await self.output.settle()
        self.output.boundary()
        if stop_reason.note:
            await self.present_help_note(
                stop_reason.note.replace("$AGENT", (self.agent_title or "agent").title()))
        if self.app.settings.notifications.turn_over:
            self.app.input_attention.notify(
                f"{self.agent_title} has finished working", title="Waiting for input",
                sound="turn-over")

    async def submission_request_failed(self, error, text: str) -> None:
        """The prompt never reached the agent: it goes back into the composer and the error
        shows under the turn."""
        self.turns.finish_client()
        if self.composer is not None:
            self.composer.restore_draft(text)
        await self.present_error_note("Internal error", str(error) or "no details were provided")

    def jump_to_latest(self) -> None:
        self.messages.jump_to_latest()

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
        """The launch's current initial identity, read fresh on each access."""
        return self.launch.initial_identity(NoThreadIdentity())

    @property
    def origin(self) -> SessionOrigin:
        return NoSessionOrigin(self.mode)

    def transcript_scope(self) -> TranscriptScope:
        """The transcript scope this view is bound to: the identity owns it directly."""
        return self.thread_identity.transcript_scope()

    def shown(self, window, visited) -> None:  # type: ignore[override]
        """Selected: record the visit, and the first time, attach the launch's agent."""
        if self.session_details is not None:
            visited(self.session_details.identity)
        if not self._attached:
            self._attached = True
            self.launch.attach_to(self, self)
        self.reload()

    def reload(self) -> None:
        """A transcript's source is live-bound by ``NativeSessionEntry.__call__``; if no
        source has been initialised, the history window just stays empty."""


class QtNativeSessionEntry(QtSessionEntry, NativeSessionEntry, shows=(SessionTabIdentity,)):
    """Qt entry for an agent session tab (``AcpTab``, ``MailboxTab``). Keeps
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


__all__ = ("QtAcpSessionView", "QtNativeSessionEntry", "CommsTab")
