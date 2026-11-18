"""The Qt conversation: what Textual's `Conversation` is, for every Qt tab's view.

Textual draws a thread's conversation and a channel's with one `Conversation`; its channel
view `CommsChatView` overrides only where the wire differs. Qt's views inherit this the
same way: `QtThreadView` adds the transcript a thread publishes through `BoundView`, and
`ConversationView` the wire history a channel or direct message reads. Everything they
both are lives here once: the thread-binding chain (`ThreadBindingDispatch`,
`ConversationThreadReadMixin`, `TranscriptView`), the rows every prompt stack has (the
flash and the activity sweep), the submissions the composer sends through, and the slash
commands it offers.
"""
from __future__ import annotations

import asyncio

import shiboken6
from textual.content import Content

from functools import partial

import shiboken6
from agent_comms.registry.thread_presentation import NoThreadPresentation, ThreadPresentation
from agent_comms.ui_model.message_category import all_categories
from metaclass_registry.mro_dispatch import MroDispatch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.agent_turn_events import AgentTurnEvents
from toad.answer import Ask
from toad.qt.agent_surface import QtSurfaceBinding, subscribe_agent
from toad.client.agent_bound import ObservedAgentBinding
from toad.client.bus_submission import TypedText
from toad.client.category_selection import CategorySelection
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.history_rows_view import AsyncioPublications
from toad.client.observed_field import ObservedField
from toad.client.prompt_composer import ComposerStatus
from toad.client.prompt_stack import ErrorTone, SuccessTone
from toad.client.session_sources import SessionSources, SourcedConversation
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.client.view_settings import ConversationSettingsOwner
from toad.command_catalog import CommandCatalog, CommandRead
from toad.conversation_submission import ConversationSubmissions
from toad.conversation_turn import ConversationTurn
from toad.flash_host import FlashHost
from toad.history_jump import JumpsHistory, JumpsToLatest
from toad.prompt_actions import SubmitInputAction
from toad.qt.activity import QtObservedSweep
from toad.qt.composer import Composer, ComposerHost
from toad.qt.core_events import QtCoreObserver
from toad.qt.history import QtHistoryNotifications, QtHistoryWindow
from toad.qt.live_turn import QtLiveBlock, QtThoughtBlock, QtUserInputBlock
from toad.qt.page import Page
from toad.qt.prompt_stack import QtFlash
from toad.qt.submission_view import QtSubmissionView
from toad.qt.view_settings import QtViewSettings
from toad.status_thread import StatusThread, WorkingStatusOwner
from toad.transcript_publication import TranscriptPresentation
from toad.turn_presentation import TurnPresentation
from toad.live_output import LiveOutput
from toad.view_actions import ViewAction
from toad.transcript_scope import TranscriptScope, TranscriptView
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame


class QtConversation(
    AgentTurnEvents,
    QtViewSettings,
    CategorySelection,
    WorkingStatusOwner,
    ComposerStatus,
    ConversationSettingsOwner,
    ObservedAgentBinding,
    ConversationThreadReadMixin,
    ThreadBindingDispatch,
    TranscriptView,
    QtCoreObserver,
    MroDispatch,
    AsyncioPublications,
    SourcedConversation,
    QtSubmissionView,
    Page,
    WorkspaceHosted,
    ComposerHost,
    QtHistoryNotifications,
    FlashHost,
    TurnPresentation,
    JumpsHistory,
    QWidget,
    metaclass=PyQtWidgetMeta,
):
    """Textual's `Conversation` on Qt. A subclass assigns `self.app`, calls
    `_setup_conversation(app)`, then builds its history and lays out its rows: the window
    (`messages`), the flash (`feedback`), the sweep (`agent_activity`), its composer and
    the observing rows under the transcript (`activity`)."""

    agent_binding: ObservedField[AgentConnection] = ObservedField(NoAgentConnection())
    thread_presentation: ThreadPresentation = NoThreadPresentation()
    """The agent thread's latest settled presentation."""
    _unpublished_presentation: ThreadPresentation = NoThreadPresentation()
    """An observed presentation whose transcript refresh waits for this view to be shown."""
    composer: Composer | None = None
    """Textual's prompt; a thread view mounts it one Qt tick after construction."""
    activity: tuple[QWidget, ...]
    """The rows under the transcript that observe Core, each closed with the view."""

    def _setup_conversation(self, app) -> None:
        """What `Conversation.compose` makes for every conversation: the window, the
        transcript presentation, the flash, the activity sweep and the submissions."""
        self.messages = QtHistoryWindow(app.renderer, self)
        self.transcript = TranscriptPresentation()
        # The categories this view's history shows (`CategorySelection`); the history reads
        # them through `selected_categories` from its first page.
        self.visible_categories = all_categories()
        self.turns = ConversationTurn(self._turn_changed, lambda: self.agent_binding.presentation.turns)
        # The turn's live streams, as Textual's `Conversation.output`: drawn as rows here.
        self.output = LiveOutput(self)
        # Where input and queue go; the opener swaps in mailbox sources for a CLI thread.
        self.operational_sources = SessionSources()
        self.feedback = QtFlash(app, app.renderer)
        self.agent_activity = QtObservedSweep(self.working, renderer=app.renderer)
        self.submissions = ConversationSubmissions(self)
        # Every conversation answers the workspace's `ViewAction` keys, as Textual's
        # `WorkspaceFrame` does for whichever conversation it shows: each member whose
        # declared capability this view has binds through the shared family loop, so
        # `BackToBottomAction` (Escape) jumps this view's window in a channel, a thread or
        # an agent session alike. A member declared for Textual's workspace DOM is not bound.
        self._view_shortcuts = app.action_keys.bind_family(self, ViewAction, self)

    @property
    def back_to_bottom_windows(self) -> tuple[JumpsToLatest, ...]:
        """The conversation's one history window, if it has scrolled off the tail
        (`JumpsHistory`): `BackToBottomAction.apply(self)` jumps it to its latest row."""
        return (self.messages,) if self.messages.can_jump_to_latest else ()

    def close_core_events(self) -> None:
        """The view's subscriptions end, the rows under the transcript stop observing, and
        a command read in flight is dropped: it would hand its catalog to a deleted
        composer. Reads are exclusive across views, so the one running may be another
        tab's; that composer asks again on its next keystroke (`Composer.refresh_offers`)."""
        super().close_core_events()
        for row in self.activity:
            row.close_activity()
        self.app.cancel_operations(CommandRead)
        self.app.coordination_access.stop_notifications(self)

    def history_loading(self) -> bool:
        """As Textual's `Conversation`: only wire histories page in under a loading row."""
        return False

    def sync_working(self) -> None:
        """Textual's `Conversation.sync_working`: the sweep reads the one `working()` answer."""
        self.agent_activity.sync()

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

    def present_thread_status(self) -> None:
        """A native agent reports its configuration through ACP (Textual's
        `OperationalSessionSources.thread_presented`); a CLI thread overrides."""

    def apply_bound_agent(self, agent) -> None:
        """A late-bound agent: the status thread and working answer are read again."""
        self.refresh_thread_status()
        self.sync_working()

    def agent_connected(self, agent) -> None:
        """A view with no connect event announces nothing; the ACP view flashes its notice."""

    # ---- The bound agent: its stream, its surface and its questions ----

    @property
    def operational_binding(self) -> AgentConnection:
        """The agent this view runs (`SessionScope.operational_binding`)."""
        return self.agent_binding

    def agent_surface(self, events) -> QtSurfaceBinding:
        """The surface the bound agent presents its tools, permissions and terminals on."""
        return QtSurfaceBinding(self, events)

    def subscribe_agent(self, events):
        """Receive the bound agent's whole stream on Qt's loop, through this view's own
        declared handlers (`AgentTurnEvents` and the view's own)."""
        return subscribe_agent(self, events)

    def publish_core(self, event) -> None:
        """Textual publishes a conversation's own events to its message pump, where its
        screen hears them; a Qt view's own handlers are the only listeners."""
        asyncio.ensure_future(self.dispatch(event))

    def request_permissions(self, request) -> None:
        """Present the request through the agent's surface: it asks in this view's question."""
        self.run_worker(partial(request.present, self), group="permission", exclusive=False)

    def ask(self, options, title: str = "", get_content=None, callback=None) -> Ask:
        """Textual's `Conversation.ask`: the question under the composer lists the options and
        fires `callback(answer)` on a pick. Returns the Ask for its asker to retract."""
        ask = Ask(title, options, get_content, callback)
        self.question.update(ask)
        return ask

    def retract(self, ask: Ask) -> None:
        """The asker withdrew `ask` (answered elsewhere, or its request ended)."""
        self.question.withdraw(ask)

    # ---- ComposerHost: where typed input goes, and the commands offered after a / ----

    def submit(self, text: TypedText, action: SubmitInputAction) -> None:
        """The composer's input enters the view's submissions, as Textual's prompt's
        `UserInputSubmitted` reaches `Conversation.submissions.submit`. No Qt view runs a
        shell, so typed input is never a shell command."""
        event = action.submission_event(text.text, False)
        self.run_worker(partial(self.submissions.submit, event), group="submit", exclusive=False)

    def update_slash_commands(self) -> None:
        """The composer asks for the commands it offers after a /."""
        self.app.run_operation(CommandRead, self.read_commands)

    async def read_commands(self) -> None:
        catalog = await self.read_command_catalog()
        if self.composer is not None:
            self.composer.set_commands(catalog.commands)

    async def read_command_catalog(self) -> CommandCatalog:
        """Textual's `Conversation.read_command_catalog`: the bound agent's advertised
        commands with this view's local ones, applicable to its target context."""
        return await CommandCatalog.read(
            self.app, self.agent_binding.presentation.commands, self.command_target_context(),
            self.local_commands)

    def flash(self, text: str) -> None:
        self.feedback.flash(text)

    def flash_success(self, text: str) -> None:
        self.feedback.flash(text, style=SuccessTone.declared_name)

    def flash_error(self, text: str) -> None:
        self.feedback.flash(text, style=ErrorTone.declared_name)

    # ---- TurnPresentation: the shared turn code's blocks, as history rows ----

    @property
    def shows_live_output(self) -> bool:
        return shiboken6.isValid(self)

    def after_live_output(self, finish) -> None:
        asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(finish()))

    async def present_user_input(self, text: str) -> None:
        self.messages.show_live(QtUserInputBlock(self.messages, text))

    def response_block(self, fragment: str, delivery) -> QtLiveBlock:
        return QtLiveBlock(self.messages, fragment)

    def thought_block(self, fragment: str) -> QtLiveBlock:
        return QtThoughtBlock(self.messages, fragment)

    async def show_live_block(self, block, stream) -> None:
        self.messages.show_live(block)

    async def present_error_note(self, message: str, details: str) -> None:
        heading = Content.from_markup(message).plain if message else ""
        text = " — ".join(part for part in (heading and f"**{heading}**", details.strip()) if part)
        block = QtLiveBlock(self.messages, text)
        block.finished = True
        self.messages.show_live(block)
        self.flash_error(heading or details.strip())

    async def present_help_note(self, markdown: str) -> None:
        block = QtLiveBlock(self.messages, markdown)
        block.finished = True
        self.messages.show_live(block)

    async def present_log_link(self, markdown: str) -> None:
        await self.present_help_note(markdown)

    # ---- The thread-binding chain ----

    @property
    def thread_scope(self) -> TranscriptScope:
        """Textual's `Conversation.thread_scope`: the scope the transcript is bound to;
        `NoTranscript` while unbound and on a wire view, which publishes no transcript."""
        return self.transcript.binding.thread_scope

    def status_thread(self) -> StatusThread:
        """`ConversationThreadReadMixin.consume_thread_presentation` opens the thread's
        status by this name, as Textual's `Conversation.status_thread`."""
        return self.thread_scope.status_thread(self.app.coordination_access)

    def thread_presented(self, presentation: ThreadPresentation) -> None:
        """A settled member owns whether this view has source work to publish, as
        Textual's `Conversation.thread_presented`."""
        self.thread_presentation = presentation
        self.refresh_thread_status()
        self.present_thread_status()
        self.dispatch_sync(presentation)

    def transcript_changed(self) -> None:
        """The thread's source changed outside this view: its sources say what to read
        again, as Textual's `Conversation.transcript_changed`."""
        self.operational_sources.external_transcript_changed(self)

    # ---- The Qt widget answers ----

    @property
    def screen(self) -> WorkspaceFrame:
        return QWidget.window(self)

    @property
    def window(self) -> QtHistoryWindow:
        """The scroll surface, as Textual's `Conversation.window`. Shadows `QWidget.window`;
        the workspace frame is reached through `QWidget.window(self)` in `screen`."""
        return self.messages

    @property
    def contents(self) -> QtConversation:
        """The view holds its history's notification targets itself."""
        return self

    def call_later(self, callback, *args) -> bool:
        if not self.is_attached:
            return False
        QTimer.singleShot(0, partial(callback, *args))
        return True

    def after_refresh(self, callback) -> None:
        QTimer.singleShot(0, callback)

    @property
    def is_attached(self) -> bool:
        """True until the Qt widget tears down, as Textual's `Widget.is_attached`. A widget
        whose C++ side Qt already deleted is not attached: asking it anything else would
        dereference the freed object."""
        return shiboken6.isValid(self) and (self.isVisible() or self.parent() is not None)

    @property
    def is_leaving(self) -> bool:
        return not self.is_attached

    @property
    def is_current_session(self) -> bool:
        """Whether this view is the one on screen; a hidden tab stashes its presentation
        for its next show."""
        return self.app.workspace_sessions.selected is self

    # ---- Its tab's settings ----

    def categories_changed(self) -> None:
        self.message_history.apply_filter()

    @property
    def configuration_identity(self):
        return self.app.session_navigation.get(self.mode).identity

    @property
    def configuration_settings(self):
        return self.app.saved_settings

    @property
    def navigation_project(self):
        return self.app.project_dir

