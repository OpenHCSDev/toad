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
import inspect
from collections.abc import Callable

from functools import partial

import shiboken6
from textual.content import Content
from agent_comms.registry.thread_presentation import NoThreadPresentation, ThreadPresentation
from agent_comms.ui_model.message_category import all_categories
from metaclass_registry.mro_dispatch import MroDispatch
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.agent_binding import AgentConnection, NoAgentConnection
from toad.agent_turn_events import AgentTurnEvents
from toad.answer import Ask
from toad.qt.agent_surface import QtSurfaceBinding, subscribe_agent
from toad.qt.metrics import UiGap
from toad.client.agent_bound import ObservedAgentBinding
from toad.client.bus_submission import TypedText
from toad.client.category_selection import CategorySelection
from toad.client.conversation_session_binding import ConversationThreadReadMixin
from toad.client.history_rows_view import AsyncioPublications
from toad.client.line_blocks import LineLink
from toad.client.observed_field import ObservedField
from toad.client.prompt_composer import ComposerStatus
from toad.client.session_sources import SessionSources, SourcedConversation
from toad.client.thread_binding_dispatch import ThreadBindingDispatch
from toad.client.view_settings import ConversationSettingsOwner
from toad.command_catalog import CommandRead, ReadsCommandCatalog
from toad.commit_claims import StartedInputClaim
from toad.conversation_comms_handlers import ConversationCommsHandlers
from toad.conversation_submission import ConversationSubmissions
from toad.conversation_turn import ConversationTurn
from toad.history_jump import JumpsHistory, JumpsToLatest
from toad.menus import MenuCommand, MenuConversation
from toad.prompt_actions import SubmitInputAction
from toad.qt.activity import QtObservedSweep
from toad.qt.composer import Composer, ComposerHost
from toad.qt.core_events import QtCoreObserver
from toad.qt.history import QtHistoryNotifications, QtHistoryWindow
from toad.qt.live_turn import QtLiveBlock, QtResponseBlock, QtThoughtBlock, QtUserInputBlock
from toad.qt.menu import QtMenu
from toad.qt.page import Page
from toad.qt.goal import QtGoalBar
from toad.qt.prompt_stack import QtFlash
from toad.qt.submission_view import QtSubmissionView
from toad.qt.view_settings import QtViewSettings
from toad.status_thread import StatusThread, WorkingStatusOwner
from toad.transcript_publication import TranscriptPresentation
from toad.turn_presentation import TurnPresentation
from toad.live_output import LiveOutput
from toad.view_actions import ViewAction
from toad.transcript_scope import TranscriptScope, TranscriptView
from toad.qt.workspace_frame import QtWorkspaceHosted


class ComposerPlaceholder(QWidget):
    """A view's composer until it is built (`QtConversation.reserve_composer`): as tall as
    that kind's composer last was, so nothing moves when it arrives. A tap or the focus on
    it builds the composer at once and hands it the focus."""

    def __init__(self, view: QtConversation, height: int) -> None:
        super().__init__()
        self.view = view
        self.setFixedHeight(height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.view.mount_composer(focus=True)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self.view.mount_composer(focus=True)


class QtConversation(
    ConversationCommsHandlers,
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
    QtWorkspaceHosted,
    ReadsCommandCatalog,
    ComposerHost,
    QtHistoryNotifications,
    MenuConversation,
    TurnPresentation,
    JumpsHistory,
    QWidget,
    metaclass=PyQtWidgetMeta,
):
    """Textual's `Conversation` on Qt. A subclass assigns `self.app`, calls
    `_setup_conversation(app)`, then builds its history and lays out its rows: the window
    (`messages`), the flash (`feedback`), the sweep (`agent_activity`), its composer and
    the observing rows under the transcript (`activity`)."""

    def workspace_navigation_owner(self, views):
        """A conversation tab navigates as its view (`ConversationView` and `QtThreadView`
        are `NavigationOwner`s, as Textual's views are)."""
        return self

    agent_binding: ObservedField[AgentConnection] = ObservedField(NoAgentConnection())
    thread_presentation: ThreadPresentation = NoThreadPresentation()
    """The agent thread's latest settled presentation."""
    _unpublished_presentation: ThreadPresentation = NoThreadPresentation()
    """An observed presentation whose transcript refresh waits for this view to be shown."""
    composer: Composer | None = None
    """Textual's prompt, built just after the view's history first paints
    (`reserve_composer`); None until then."""
    composer_heights: dict[type, int] = {}
    """Each view kind's composer height when it was last built: the placeholder's height, so
    nothing moves when the composer arrives. Shared by every view of the kind."""
    _composer_reserved: tuple | None = None
    activity: tuple[QWidget, ...]
    """The rows under the transcript that observe Core, each closed with the view."""
    goal_bar: QtGoalBar | None = None
    """Textual's `GoalBar`; `None` for a view with no managed thread or DM peer."""

    def _setup_conversation(self, app) -> None:
        """What `Conversation.compose` makes for every conversation: the window, the
        transcript presentation, the flash, the activity sweep, the block menu and the submissions."""
        self.held_fragment = None
        self.messages = QtHistoryWindow(app.renderer, app.row_pictures, self)
        self.messages.block_menu_requested.connect(self.open_block_menu)
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
        self.agent_activity = QtObservedSweep(
            self.working, renderer=app.renderer, clock=app.animation_clock)
        self.submissions = ConversationSubmissions(self)
        # What the composer is told before it is built, the latest of each kind, told at
        # its mount (`on_composer`).
        self._composer_applies: dict[str, Callable[[Composer], None]] = {}
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

    # ---- The composer: built once the view's history has painted ----

    def reserve_composer(self, layout: QBoxLayout, build: Callable[[], Composer],
                         mounted: Callable[[Composer], None]) -> None:
        """The composer's place in `layout`, held by a placeholder as tall as this kind's
        composer last was. The composer is built just after the history first paints, so
        opening a view draws its history without waiting for the composer (a channel's took
        170 ms of a 491 ms open at a phone's speed), and a view never shown (a restored tab
        in the background) builds none until it is. On Qt-for-Android this also keeps
        ``QPlainTextEdit`` out of the first frame's EGL setup, which it deadlocks against
        (``QtAndroidAccessibility``). `mounted` places what goes with it."""
        placeholder = ComposerPlaceholder(self, self.composer_heights.get(type(self), self.estimated_composer_height()))
        layout.addWidget(placeholder)
        self._composer_reserved = (layout, placeholder, build, mounted)
        self.messages.viewport().installEventFilter(self)

    def estimated_composer_height(self) -> int:
        """Before any composer of this kind was built: its editor (one line and the padding
        `Composer.fit_height` gives it) over its info bar (a line and its margin)."""
        line = self.fontMetrics().lineSpacing()
        return (line + 24) + (line + UiGap.tight)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if (event.type() == QEvent.Type.Paint and self._composer_reserved is not None
                and watched is self.messages.viewport()):
            watched.removeEventFilter(self)
            QTimer.singleShot(0, self.mount_composer)
        return super().eventFilter(watched, event)

    def mount_composer(self, focus: bool = False) -> None:
        """Build the reserved composer in its placeholder's place, then tell it what it was
        told meanwhile. Touching the placeholder mounts it at once, with the focus, so
        typing never waits. A failed mount is loud: a silently missing composer is how the
        mailbox view first shipped."""
        reserved, self._composer_reserved = self._composer_reserved, None
        if reserved is None or not shiboken6.isValid(self):
            return
        layout, placeholder, build, mounted = reserved
        self.messages.viewport().removeEventFilter(self)
        try:
            composer = build()
        except Exception as error:
            self.app.show_error(error, "Composer mount failed")
            return
        layout.replaceWidget(placeholder, composer)
        placeholder.deleteLater()
        self.composer = composer
        mounted(composer)
        applies, self._composer_applies = self._composer_applies, {}
        for apply in applies.values():
            apply(composer)
        if focus:
            composer.editor.setFocus()
        QTimer.singleShot(0, partial(self.remember_composer_height, composer))

    def remember_composer_height(self, composer: Composer) -> None:
        """The height the composer asks for, not the room it was given: a view whose
        transcript is not laid out yet lets it stretch."""
        if shiboken6.isValid(composer):
            self.composer_heights[type(self)] = composer.sizeHint().height()

    def on_composer(self, kind: str, apply: Callable[[Composer], None]) -> None:
        """Tell the composer something: now once it is built, else at its mount, where only
        the latest of each `kind` is told (a label, a status, the mention candidates)."""
        if self.composer is not None:
            apply(self.composer)
        else:
            self._composer_applies[kind] = apply

    def close_core_events(self) -> None:
        """The view's subscriptions end, the rows under the transcript stop observing, and
        a command read in flight is dropped: it would hand its catalog to a deleted
        composer. Reads are exclusive across views, so the one running may be another
        tab's; that composer asks again on its next keystroke (`Composer.refresh_offers`).
        A composer not built yet never will be."""
        self._composer_reserved = None
        self._composer_applies.clear()
        super().close_core_events()
        for row in self.activity:
            row.close_activity()
        self.app.cancel_operations(CommandRead)
        self.app.coordination_access.stop_notifications(self)
        self.message_history.retire_source()

    def sync_working(self) -> None:
        """Textual's `Conversation.sync_working`: the sweep reads the one `working()` answer."""
        self.agent_activity.sync()

    def goal_changed_from(self, publisher: object) -> None:
        """Invalidate this view's goal bar (thread or DM peer) when a GoalChangedUpdate arrives."""
        if self.goal_bar is not None:
            self.goal_bar.goal_observation.invalidate_from(publisher)

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
        """The info bar shows `ComposerStatus.composed_status()`, once the composer exists."""
        self.on_composer("status", lambda composer: composer.show_status(self.composed_status()))

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
        event = action.submission_event(text.text, False, text.files)
        self.run_worker(self.submissions.received(event), group="submit", exclusive=False)

    def update_slash_commands(self) -> None:
        """The composer asks for the commands it offers after a /."""
        self.app.run_operation(CommandRead, self.read_commands)

    async def read_commands(self) -> None:
        catalog = await self.read_command_catalog()
        self.on_composer("commands", lambda composer: composer.set_commands(catalog.commands))

    def command_navigation(self):
        return self.navigation_context

    # ---- TurnPresentation: the shared turn code's blocks, as history rows ----

    @property
    def shows_live_output(self) -> bool:
        return shiboken6.isValid(self)

    def after_live_output(self, finish) -> None:
        asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(finish()))

    async def present_user_input(self, text: str) -> None:
        self.messages.show_live(QtUserInputBlock(self.messages, text))

    async def present_started_user_input(self, started) -> None:
        self.messages.show_live(
            QtUserInputBlock(self.messages, started.text, claim=StartedInputClaim(started))
        )

    def restore_composer_draft(self, text: str) -> None:
        self.on_composer("draft", lambda composer: composer.restore_draft(text))

    def coordination_synced(self) -> None:
        self.sync_status()
        self.on_composer("queue", lambda composer: composer.sync_queue())

    async def present_turn_cancelled(self, feedback: str) -> None:
        await self.present_help_note(f"## Turn cancelled\n\n{feedback}")

    def response_block(self, fragment: str, delivery) -> QtResponseBlock:
        return QtResponseBlock(self.messages, fragment)

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

    def thread_presented(self, presentation: ThreadPresentation) -> None:
        """A settled member owns whether this view has source work to publish, as
        Textual's `Conversation.thread_presented`."""
        self.thread_presentation = presentation
        self.refresh_thread_status()
        self.present_thread_status()
        self.dispatch_sync(presentation)

    # ---- The Qt widget answers ----

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
        """Textual's `call_later`: after the work already queued, and a coroutine callback
        (a turn's `AgentSubmissionExecution.complete`) is awaited, not dropped."""
        if not self.is_attached:
            return False
        QTimer.singleShot(0, partial(self.called_later, callback, args))
        return True

    def called_later(self, callback, args) -> None:
        if inspect.isawaitable(result := callback(*args)):
            self.run_worker(lambda: result, group="call_later")

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
    def configuration_mode(self):
        return self.mode

    @property
    def navigation_project(self):
        return self.app.project_dir

    # ---- Block menu — MenuConversation implementation shared by channels, DMs, mailboxes and ACP tabs ----

    def open_block_menu(self, fragment, pressed: QPoint) -> None:
        """The block menu for `fragment`, at `pressed` (the window's coordinates)."""
        self.held_fragment = fragment
        entries = QtMenu.command_entries(
            QtMenu.block_commands(fragment, fragment.block_menu),
            self.app.settings,
            self._run_block_menu_command,
        )
        if entries:
            self.app.offer_entries(entries, QRect(pressed, QSize(1, 1)))

    def _run_block_menu_command(self, command: MenuCommand) -> None:
        result = command.apply(self)
        if asyncio.iscoroutine(result):
            self.app.run_menu_action(lambda: result)

    def accepts_menu_owner(self, owner: QWidget) -> bool:
        return self.held_fragment is not None

    def block_clipboard_text(self) -> str:
        return self.held_fragment.clipboard_text if self.held_fragment is not None else ""

    def block_prompt_text(self) -> str:
        return self.block_clipboard_text()

    def append_to_prompt(self, text: str) -> None:
        """Into the composer where its cursor is; a composer not built yet takes it at its
        mount (`on_composer`)."""
        self.on_composer("block text", partial(self.type_in_composer, text))

    @staticmethod
    def type_in_composer(text: str, composer: Composer) -> None:
        composer.editor.textCursor().insertText(text)
        composer.editor.setFocus()

    def maximize_block(self) -> None:
        """Qt has no maximize mode yet; the command is offered but logs a notice."""
        self.app.show_info("Maximize is Textual-only for now", "Block")

    def export_block_to_svg(self) -> None:
        """Qt has no SVG export yet; the command is offered but logs a notice."""
        self.app.show_info("SVG export is Textual-only for now", "Block")

    async def interrupt_shell(self) -> None:
        """No shell blocks render on Qt yet, so interrupt is a no-op here."""

    def open_line_link(self, link: LineLink) -> None:
        """Dispatch the declared `LineLink` through `QtHistoryWindow` (`OpensLineLinks`)."""
        self.messages.dispatch_sync(link)

