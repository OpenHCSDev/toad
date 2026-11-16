"""The Qt window: the bus's threads, and Toad's tabs over the conversations you open.

Tabs, their saved roster and back/forward history are Toad's own TabOrder over CommsTab
identities; each tab is the shared conversation entry, drawn by a Qt ConversationView.
"""

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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScroller,
    QStackedWidget,
    QTabBar,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ui_theme.scheme import (
    BackgroundColour,
    ColourScheme,
    ForegroundColour,
    PrimaryColour,
    ThemeColour,
)

from toad.client.connection import CoordinationAccess, FailedObservation, Observing
from toad.client.conversation import ChannelConversation, ConversationKind, DmConversation
from toad.client.conversation_capabilities import ConversationSource
from toad.client.db import DB
from toad.client.history_entry import SharedHistorySessionEntry
from toad.client.line_blocks import LineBlock
from toad.client.subscribers import SidebarSubscriber
from toad.client.tab_identity import TabIdentity
from toad.client.tab_identity.kinds import CommsTab
from toad.client.tab_order import TabOrder
from toad.constants import WELCOME
from toad.core.events import CoordinationObserved, TabHistoryChanged
from toad.message_rows import MarkdownMessageStyle, MessageRow
from toad.qt.lines import QtLineRenderer


class ConversationRead(OperationKind, ExclusiveKind):
    """Reads the shown conversation's newest page; a newer read supersedes the running one."""


class ConversationOpen(OperationKind, ExclusiveKind):
    """Opens a tapped row's conversation in its tab; a newer tap supersedes the running one."""


class MessageSend(OperationKind):
    """Sends one message; sends run side by side and are never superseded."""


class TabClose(OperationKind):
    """Closes one tab; closes run side by side."""


@dataclass(frozen=True)
class ObservedSource(ConversationSource):
    """The observed Core's reads, in the project this window views."""

    core: CoreAccess
    root: Path
    project: Checkout


class ConversationRow(QListWidgetItem):
    """One sidebar row, drawing the conversation it opens."""

    def __init__(self, kind: type[ConversationKind], name: str, label: str) -> None:
        super().__init__(label)
        self.target = RowTarget(kind, name, label)


@dataclass(frozen=True)
class RowTarget:
    """What a tapped row opens, held apart from the row: a repaint deletes the row's Qt item
    while its conversation is still resolving."""

    kind: type[ConversationKind]
    name: str
    label: str


class TouchScrolled:
    """A scroll area a finger scrolls, kinetically. Qt widgets on Android scroll only by
    scroll bar unless a QScroller holds the viewport."""

    def __init__(self) -> None:
        super().__init__()
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)


class Page:
    """A page of the window: shown when selected, read again when Core's stores change."""

    def reload(self) -> None:
        """A page fed by its own subscription has nothing to read again."""


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


class ThreadList(Page, TouchList, SidebarSubscriber[Observing, FailedObservation]):
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
            self.addItem(ConversationRow(ChannelConversation, name, str(name)))
        for name in model.threads.rows:
            self.addItem(ConversationRow(DmConversation, name, f"@{name}"))
        self.window.label_tabs(self.observed)

    def open_row(self, row: ConversationRow) -> None:
        self.window.open_row(row)


class QtHistorySessionEntry(SharedHistorySessionEntry["CommsWindow"]):
    """The shared conversation entry, drawn in this window's ConversationView."""

    def __init__(self, window: CommsWindow, identity: CommsTab, opened) -> None:
        super().__init__(identity, opened.key, window.project, opened.viewer, opened.participants)
        self.window = window

    def __call__(self) -> ConversationView:
        return ConversationView(self.window, self)


class ConversationView(Page, QWidget):
    """One conversation tab: its newest page, read again whenever Core's stores change, and
    a sender."""

    page_size = 50

    def __init__(self, window: CommsWindow, entry: QtHistorySessionEntry) -> None:
        super().__init__()
        self.window, self.entry = window, entry
        self.tab = entry.unobserved_tab()
        self.messages = MessageView(window.renderer)
        self.input = QLineEdit()
        self.input.setPlaceholderText(f"Message {self.tab.label()}")
        self.input.returnPressed.connect(self.send)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        footer = QHBoxLayout()
        footer.addWidget(self.input, 1)
        footer.addWidget(send)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.messages, 1)
        layout.addLayout(footer)

    @property
    def conversation(self) -> ConversationKind:
        return self.entry.key.conversation

    def reload(self) -> None:
        self.window.access.app.run_operation(ConversationRead, self.read_page)

    async def read_page(self) -> None:
        source = self.window.source()
        page: MessagePage = await asyncio.to_thread(
            self.conversation.page, source, PageBounds(limit=self.page_size))
        style = MarkdownMessageStyle()
        rows = (MessageRow(message, self.entry.viewer) for message in page.messages)
        self.messages.show_blocks(tuple(
            block for row in rows for block in (row.header, *style.body(row, row.text))))

    def send(self) -> None:
        body = self.input.text().strip()
        if not body:
            return
        self.input.clear()
        self.window.access.app.run_operation(MessageSend, partial(self.deliver, body))

    async def deliver(self, body: str) -> None:
        observed = self.window.access.observation.observed()
        await asyncio.to_thread(observed.send_user_message, self.conversation.send_target(), body)
        self.reload()


class CommsWindow(QWidget):
    """The threads, and a tab per open conversation; the bar under them is Toad's: the
    menu button, back and forward through the visit history, and the tabs."""

    def __init__(self, access: CoordinationAccess, scheme: ColourScheme, db: DB) -> None:
        super().__init__()
        self.setWindowTitle("Toad")
        self.access = access
        self.project = access.app.project_dir
        self.renderer = QtLineRenderer(scheme)
        self.setPalette(self.palette_of(scheme))
        self.tab_order = TabOrder(self.show_tab, home=WELCOME, db=db,
                                  scopes=access.connection.tab_scopes())
        self.views: dict[TabIdentity, ConversationView] = {}
        self.threads = ThreadList(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.threads)
        self.menu = self.bar_button("☰", "Threads", self.show_threads)
        self.back = self.bar_button("←", "Back", partial(self.tab_order.navigate, -1))
        self.forward = self.bar_button("→", "Forward", partial(self.tab_order.navigate, 1))
        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBarClicked.connect(self.visit_index)
        self.tabs.tabCloseRequested.connect(self.close_index)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        for widget in (self.menu, self.back, self.forward):
            bar.addWidget(widget)
        bar.addWidget(self.tabs, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages, 1)
        layout.addLayout(bar)
        self.changes = access.events.subscribe(CoordinationObserved, self.stores_changed)
        self.history = self.tab_order.events.subscribe(TabHistoryChanged, self.history_changed)
        self.history_changed()
        self.android_back = QShortcut(QKeySequence(Qt.Key.Key_Back), self, self.go_back,
                                      context=Qt.ShortcutContext.ApplicationShortcut)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.go_back,
                                context=Qt.ShortcutContext.ApplicationShortcut)
        self.winId()
        self.windowHandle().safeAreaMarginsChanged.connect(self.fit_safe_area)
        self.fit_safe_area(self.windowHandle().safeAreaMargins())

    def bar_button(self, text: str, tip: str, action) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.clicked.connect(action)
        return button

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
        self.pages.currentWidget().reload()

    def history_changed(self, *event: object) -> None:
        """Back and forward are live exactly when the visit history has a step that way."""
        self.back.setEnabled(self.tab_order.history_target(-1) is not None)
        self.forward.setEnabled(self.tab_order.history_target(1) is not None)

    def source(self) -> ObservedSource:
        observed = self.access.observation.observed()
        return ObservedSource(observed.core, observed.root, self.project)

    # Tabs: TabOrder owns their order, the saved roster and the visit history.

    @property
    def shown(self) -> tuple[ConversationView, ...]:
        """The open tabs this window draws, in TabOrder's order."""
        return self.tab_order.project(self.views)

    def paint_tabs(self) -> None:
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for view in self.shown:
            self.tabs.addTab(view.tab.label())
        self.tabs.blockSignals(False)
        self.mark_current()

    def label_tabs(self, observed: Observing) -> None:
        """Each tab's label from the bus's current names, as Toad's tab bar labels it."""
        for view in self.views.values():
            view.tab = view.entry.tab(self, observed)
        self.paint_tabs()

    def mark_current(self) -> None:
        current = self.pages.currentWidget()
        self.tabs.setCurrentIndex(self.shown.index(current) if current in self.shown else -1)

    def open_row(self, row: ConversationRow) -> None:
        self.access.app.run_operation(ConversationOpen, partial(self.open_target, row.target))

    async def open_target(self, target: RowTarget) -> None:
        source = self.source()
        viewer = await asyncio.to_thread(
            lambda: self.access.observation.observed().user_identity(self.project).name)
        resolved = await asyncio.to_thread(target.kind.resolve, source, viewer, target.name)
        identity = CommsTab(resolved.conversation, str(source.root))
        if identity not in self.views:
            view = (await identity.entry(self))()
            self.views[identity] = view
            self.pages.addWidget(view)
            await self.tab_order.open(identity)
            self.label_tabs(await asyncio.to_thread(self.access.observation.observed))
        self.tab_order.record_visit(identity)
        self.show_tab(identity)

    async def history_entry(self, identity: CommsTab) -> QtHistorySessionEntry:
        """Toad's entry for a conversation tab, read again on the bus that owns it."""
        opened = await asyncio.to_thread(lambda: SharedHistorySessionEntry.reopened(
            identity, self.access.observation.observed(), self.project))
        return QtHistorySessionEntry(self, identity, opened)

    def show_tab(self, identity: TabIdentity) -> None:
        view = self.views[identity]
        self.pages.setCurrentWidget(view)
        self.mark_current()
        view.reload()

    def visit_index(self, index: int) -> None:
        identity = self.shown[index].entry.identity
        self.tab_order.record_visit(identity)
        self.show_tab(identity)

    def close_index(self, index: int) -> None:
        self.access.app.run_operation(TabClose, partial(self.close_tab, self.shown[index]))

    async def close_tab(self, view: ConversationView) -> None:
        identity = view.entry.identity
        await self.tab_order.close({identity})
        del self.views[identity]
        self.pages.removeWidget(view)
        view.deleteLater()
        self.paint_tabs()
        if self.pages.currentWidget() is self.threads:
            return
        modes = {shown.mode_name: shown for shown in self.views}
        returned = self.tab_order.came_from(identity)
        if returned in modes:
            self.tab_order.record_visit(modes[returned])
            self.show_tab(modes[returned])
        else:
            self.show_threads()

    def show_threads(self) -> None:
        self.pages.setCurrentWidget(self.threads)
        self.mark_current()

    def go_back(self) -> None:
        """Android back: the visit history's previous tab; with none, the threads; at the
        threads, close the app, as back does at an app's first screen."""
        if self.tab_order.history_target(-1) is not None:
            self.tab_order.navigate(-1)
        elif self.pages.currentWidget() is not self.threads:
            self.show_threads()
        else:
            self.close()
