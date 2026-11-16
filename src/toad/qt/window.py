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
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
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
from toad.client.subscribers import SidebarSubscriber
from toad.core.events import CoordinationObserved


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


class ThreadList(QListWidget, SidebarSubscriber[Observing, FailedObservation]):
    """The bus's channels and threads, from the shared sidebar model."""

    def __init__(self, window: CommsWindow) -> None:
        super().__init__()
        self.window = window
        self.observed: Observing | None = None
        self.setWordWrap(True)
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
        self.messages = QListWidget()
        self.messages.setWordWrap(True)
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

    def show_conversation(self, conversation: SharedConversationKind, label: str) -> None:
        self.conversation = conversation
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
        self.messages.clear()
        for message in reversed(page.messages):
            self.messages.addItem(f"{message.sender}: {message.body}")
        self.messages.scrollToBottom()

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

    def __init__(self, access: CoordinationAccess) -> None:
        super().__init__()
        self.setWindowTitle("Toad")
        self.access = access
        self.threads = ThreadList(self)
        self.conversation = ConversationView(self)
        self.addWidget(self.threads)
        self.addWidget(self.conversation)
        self.changes = access.events.subscribe(CoordinationObserved, self.stores_changed)

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
        self.conversation.show_conversation(resolved.conversation, target.label)
        self.setCurrentWidget(self.conversation)

    def show_threads(self) -> None:
        self.conversation.conversation = None
        self.setCurrentWidget(self.threads)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Back, Qt.Key.Key_Escape) and self.currentWidget() is self.conversation:
            self.show_threads()
            return
        super().keyPressEvent(event)
