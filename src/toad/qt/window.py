"""The Qt window: the bus's threads, and one conversation you can read and write in."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.messaging.message_page import MessagePage, PageBounds
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from agent_comms.ui_model.sidebar import SidebarModel
from formbridge.operations import ExclusiveKind, OperationKind
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScroller,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from toad.client.connection import CoordinationAccess, FailedObservation, Observing
from toad.client.conversation import (
    SharedChannelConversation,
    SharedConversationKind,
    SharedDmConversation,
)
from toad.client.conversation_capabilities import ConversationSource
from toad.client.line_blocks import LineBlock
from toad.client.subscribers import SidebarSubscriber
from toad.core.events import CoordinationObserved
from toad.message_rows import MarkdownMessageStyle, MessageRow
from toad.qt.lines import QtLineRenderer
from ui_theme.scheme import (
    BackgroundColour,
    ColourScheme,
    ForegroundColour,
    PrimaryColour,
    ThemeColour,
)


class ConversationRead(OperationKind, ExclusiveKind):
    """Reads the open conversation's newest page; a newer read supersedes the running one."""


class ConversationOpen(OperationKind, ExclusiveKind):
    """Resolves a tapped row into its conversation; a newer tap supersedes the running one."""


class MessageSend(OperationKind):
    """Sends one message; sends run side by side and are never superseded."""


@dataclass(frozen=True)
class ObservedSource(ConversationSource):
    """The observed Core's reads, in the project this window views."""

    core: CoreAccess
    root: Path
    project: Checkout


class ConversationRow(QListWidgetItem):
    """One sidebar row, drawing the conversation it opens."""

    def __init__(self, kind: type[SharedConversationKind], name: str, label: str) -> None:
        super().__init__(label)
        self.target = RowTarget(kind, name, label)


@dataclass(frozen=True)
class RowTarget:
    """What a tapped row opens, held apart from the row: a repaint deletes the row's Qt item
    while its conversation is still resolving."""

    kind: type[SharedConversationKind]
    name: str
    label: str


class TouchScrolled:
    """A scroll area a finger scrolls, kinetically. Qt widgets on Android scroll only by
    scroll bar unless a QScroller holds the viewport."""

    def __init__(self) -> None:
        super().__init__()
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)


class TouchList(TouchScrolled, QListWidget):
    """A list a finger scrolls, by pixel, wrapping long rows."""

    def __init__(self) -> None:
        super().__init__()
        self.setWordWrap(True)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)


class MessageView(TouchScrolled, QTextBrowser):
    """A conversation's messages as Toad draws them: each row's header and body blocks,
    drawn again at a new width, since dividers fill the width."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.setOpenLinks(False)
        self.renderer = renderer
        self.blocks: tuple[LineBlock, ...] = ()

    def show_blocks(self, blocks: tuple[LineBlock, ...]) -> None:
        self.blocks = blocks
        self.paint_blocks()
        scroll = self.verticalScrollBar()
        scroll.setValue(scroll.maximum())

    def paint_blocks(self) -> None:
        self.setHtml(self.renderer.at_width(self.viewport().width() - 8, self.font()).html(self.blocks))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.paint_blocks()


class ThreadList(TouchList, SidebarSubscriber[Observing, FailedObservation]):
    """The bus's channels and threads, from the shared sidebar model."""

    def __init__(self, window: CommsWindow) -> None:
        super().__init__()
        self.window = window
        self.observed: Observing | None = None
        self.itemActivated.connect(self.open_row)
        self.itemClicked.connect(self.open_row)

    def bind_observation(self, observed: Observing) -> None:
        if self.observed is observed:
            return
        self.observed = observed
        observed.sidebar.channels.subscribe(self.rows_changed)
        observed.sidebar.threads.subscribe(self.rows_changed)
        self.window.access.show_sidebar(self, True)
        self.present()

    def rows_changed(self, changes: object) -> None:
        self.present()

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.observed = None
        self.clear()
        self.addItem(f"Bus unavailable: {type(observed.error).__name__}: {observed.error}")

    def present(self, **changes: object) -> None:
        if self.observed is None:
            return
        model: SidebarModel = self.observed.sidebar
        self.clear()
        for name in model.channels.rows:
            self.addItem(ConversationRow(SharedChannelConversation, name, str(name)))
        for name in model.threads.rows:
            self.addItem(ConversationRow(SharedDmConversation, name, f"@{name}"))

    def open_row(self, row: ConversationRow) -> None:
        self.window.open_conversation(row)


class ConversationView(QWidget):
    """One conversation's newest page, rereading whenever Core's stores change, and a sender."""

    page_size = 50

    def __init__(self, window: CommsWindow) -> None:
        super().__init__()
        self.window = window
        self.conversation: SharedConversationKind | None = None
        self.title = QLabel()
        back = QPushButton("Back")
        back.clicked.connect(window.show_threads)
        header = QHBoxLayout()
        header.addWidget(back)
        header.addWidget(self.title, 1)
        self.messages = MessageView(window.renderer)
        self.reader = ""
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message")
        self.input.returnPressed.connect(self.send)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        footer = QHBoxLayout()
        footer.addWidget(self.input, 1)
        footer.addWidget(send)
        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.messages, 1)
        layout.addLayout(footer)

    def show_conversation(self, conversation: SharedConversationKind, label: str, reader: str) -> None:
        self.conversation = conversation
        self.reader = reader
        self.title.setText(label)
        self.input.setPlaceholderText(f"Message {label}")
        self.reload()

    def reload(self) -> None:
        if self.conversation is not None:
            self.window.access.app.run_operation(ConversationRead, partial(self.read_page, self.conversation))

    async def read_page(self, conversation: SharedConversationKind) -> None:
        source = self.window.source()
        page: MessagePage = await asyncio.to_thread(
            conversation.page, source, PageBounds(limit=self.page_size))
        if conversation is not self.conversation:
            return
        style = MarkdownMessageStyle()
        rows = (MessageRow(message, self.reader) for message in page.messages)
        self.messages.show_blocks(tuple(
            block for row in rows for block in (row.header, *style.body(row, row.text))))

    def send(self) -> None:
        body = self.input.text().strip()
        if not body or self.conversation is None:
            return
        self.input.clear()
        self.window.access.app.run_operation(MessageSend, partial(self.deliver, self.conversation, body))

    async def deliver(self, conversation: SharedConversationKind, body: str) -> None:
        observed = self.window.access.observation.observed()
        await asyncio.to_thread(observed.send_user_message, conversation.send_target(), body)
        self.reload()


class CommsWindow(QStackedWidget):
    """Threads first; tapping one opens its conversation; Back returns."""

    def __init__(self, access: CoordinationAccess, scheme: ColourScheme) -> None:
        super().__init__()
        self.setWindowTitle("Toad")
        self.access = access
        self.renderer = QtLineRenderer(scheme)
        self.setPalette(self.palette_of(scheme))
        self.threads = ThreadList(self)
        self.conversation = ConversationView(self)
        self.addWidget(self.threads)
        self.addWidget(self.conversation)
        self.changes = access.events.subscribe(CoordinationObserved, self.stores_changed)
        self.back = QShortcut(QKeySequence(Qt.Key.Key_Back), self, self.go_back,
                              context=Qt.ShortcutContext.ApplicationShortcut)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.go_back,
                                context=Qt.ShortcutContext.ApplicationShortcut)
        self.winId()
        self.windowHandle().safeAreaMarginsChanged.connect(self.fit_safe_area)
        self.fit_safe_area(self.windowHandle().safeAreaMargins())

    @staticmethod
    def palette_of(scheme: ColourScheme) -> QPalette:
        """Qt's palette roles in the theme's stated colours; like Textual's colour system,
        Qt lays out the layer shades a scheme leaves to the backend."""
        def colour(member: type[ThemeColour]) -> QColor:
            return QColor(member.rgb(scheme).hex)
        palette = QPalette()
        for role, member in ((QPalette.ColorRole.Window, BackgroundColour),
                             (QPalette.ColorRole.Base, BackgroundColour),
                             (QPalette.ColorRole.AlternateBase, BackgroundColour),
                             (QPalette.ColorRole.Button, BackgroundColour),
                             (QPalette.ColorRole.Highlight, PrimaryColour),
                             (QPalette.ColorRole.WindowText, ForegroundColour),
                             (QPalette.ColorRole.Text, ForegroundColour),
                             (QPalette.ColorRole.ButtonText, ForegroundColour),
                             (QPalette.ColorRole.HighlightedText, ForegroundColour)):
            palette.setColor(role, colour(member))
        return palette

    def fit_safe_area(self, margins: QMargins) -> None:
        """Keep every row clear of the status and navigation bars."""
        self.setContentsMargins(margins)

    def stores_changed(self, event: CoordinationObserved, subscription: object) -> None:
        self.conversation.reload()

    def source(self) -> ObservedSource:
        observed = self.access.observation.observed()
        return ObservedSource(observed.core, observed.root, self.access.app.project_dir)

    def open_conversation(self, row: ConversationRow) -> None:
        self.access.app.run_operation(ConversationOpen, partial(self.resolve, row.target))

    async def resolve(self, target: RowTarget) -> None:
        source = self.source()
        me = await asyncio.to_thread(lambda: source.registry().user_thread().require(
            RuntimeError("This bus has no user thread")).name)
        resolved = await asyncio.to_thread(target.kind.resolve, source, me, target.name)
        self.conversation.show_conversation(resolved.conversation, target.label, me)
        self.setCurrentWidget(self.conversation)

    def show_threads(self) -> None:
        self.conversation.conversation = None
        self.setCurrentWidget(self.threads)

    def go_back(self) -> None:
        """Android back, from any focused widget: a conversation returns to the threads;
        the threads close the app, as back does at an app's first screen."""
        if self.currentWidget() is self.conversation:
            self.show_threads()
        else:
            self.close()
