"""The Qt application: the shared client application drawn as Toad's tabs over the
conversations you open, and its sidebar of channels and threads behind the bar above them.

Tabs open, switch and close through the shared SessionNavigation, as Textual's do: a
sidebar row is the shared history route, each tab is the shared conversation entry, and
QtWorkspaceViews draws its view, a Qt ConversationView.
"""

from __future__ import annotations

import asyncio
from time import monotonic, time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from agent_comms.messaging.message_page import MessagePage, PageBounds
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from agent_comms.ui_model.sidebar import SidebarModel
from agent_comms.ui_model.status import ThreadStatusModel
from formbridge.operations import ExclusiveKind, OperationKind
from PySide6.QtCore import QMargins, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScroller,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTextBrowser,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ui_theme.effects import ACTIVITY_SWEEP
from ui_theme.scheme import (
    BackgroundColour,
    ColourScheme,
    AlternateRowToneColour,
    ForegroundColour,
    HeaderToneColour,
    PrimaryColour,
    SidebarToneColour,
    ThemeColour,
)

from toad.client.application import ClientApplication
from toad.client.application_actions import ApplicationAction
from toad.client.bus_selection import BusChoice
from toad.client.connection import (
    CoordinationAccess,
    CoreConnection,
    FailedObservation,
    Observing,
    RemoteCoreConnection,
)
from toad.client.conversation import ConversationKind
from toad.client.conversation_capabilities import ConversationSource
from toad.client.history_entry import HistorySessionEntry
from toad.client.condensed_path import condense_path, home_relative
from toad.client.line_blocks import LineBlock, MutedRole, TextRole
from toad.client.welcome import ChannelListing, ThreadListing, WelcomeBanner
from toad.client.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.client.subscribers import SidebarSubscriber
from toad.client.tab_identity.kinds import CommsTab
from toad.constants import WELCOME
from toad.core.events import CoordinationObserved, TabHistoryChanged
from toad.message_rows import MarkdownMessageStyle, MessageRow
from toad.launch_binding import NoAgent
from toad.navigation_context import NoNavigationOwner
from toad.navigation_target import DirectTarget, HistoryRouted, channel_target
from toad.qt.core_events import QtCoreObserver
from toad.qt.host import QtCommsHost
from toad.qt.lines import QtLineRenderer
from toad.session_host import SessionEntries, SessionNavigator, WorkspaceViews
from toad.status_thread import ObservedActivity, StatusOwner
from toad.work_preparation import PreparationRuntime


class ConversationRead(OperationKind, ExclusiveKind):
    """Reads the shown conversation's newest page; a newer read supersedes the running one."""


class ConversationOpen(OperationKind, ExclusiveKind):
    """Opens a tapped row's conversation in its tab; a newer tap supersedes the running one."""


class MessageSend(OperationKind):
    """Sends one message; sends run side by side and are never superseded."""


class MenuActionRun(OperationKind):
    """One application action chosen from the menu."""


class TabClose(OperationKind):
    """Closes one tab; closes run side by side."""


@dataclass(frozen=True)
class ObservedSource(ConversationSource):
    """The observed Core's reads, in the project this window views."""

    core: CoreAccess
    root: Path
    project: Checkout


class SidebarItem(QTreeWidgetItem):
    """One line of the sidebar tree; its row widget draws it, a tap activates it."""

    key: str

    def activate(self, window: QtToadApp) -> None:
        """A group line opens and closes its group."""
        self.setExpanded(not self.isExpanded())


class SidebarSection(SidebarItem):
    """A group of rows with a title, such as Threads."""

    def __init__(self, title: str) -> None:
        super().__init__([title])
        self.key = title


class ConversationRow(SidebarItem):
    """A row that opens its conversation through the shared history route it holds."""

    def __init__(self, target: HistoryRouted) -> None:
        super().__init__()
        self.key = target.name
        self.target = target

    def activate(self, window: QtToadApp) -> None:
        window.open_row(self)


class BusRow(SidebarItem):
    """A bus the welcome lists; a tap switches the window onto it, as a row the Textual
    picker lists does."""

    def __init__(self, choice: BusChoice) -> None:
        super().__init__()
        self.key = choice.label()
        self.choice = choice

    def activate(self, window: QtToadApp) -> None:
        self.choice.chosen(window)


class TouchScrolled:
    """A scroll area a finger scrolls, kinetically. Qt widgets on Android scroll only by
    scroll bar unless a QScroller holds the viewport."""

    def __init__(self) -> None:
        super().__init__()
        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)


class Page:
    """A page of the window: shown when selected, read again when Core's stores change."""

    mode: str

    def reload(self) -> None:
        """A page fed by its own subscription has nothing to read again."""

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        """Selected: read again; a tab passes its identity to the visit history."""
        self.reload()


class QtChannelListing(ChannelListing):
    def add(self, rows: ConversationRows, section: SidebarSection, model: SidebarModel) -> None:
        for name in self.listed(model):
            rows.add_channel(section, name, model.channels.rows[name])


class QtThreadListing(ThreadListing):
    def add(self, rows: ConversationRows, section: SidebarSection, model: SidebarModel) -> None:
        for name in self.listed(model):
            rows.add_thread(section, name, model.threads.rows[name])


class Welcome(Page, QWidget):
    """Toad's welcome, while no conversation tab is open and in place of a saved tab this app
    has not opened: the banner, the project, the channels and threads the shared welcome
    lists, and the remote buses this machine holds. A Qt client is always remote, so the
    buses are BusChoice.held, the Textual welcome's own source without this machine's bus."""

    mode = WELCOME
    listings = (QtChannelListing(), QtThreadListing())

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.banner = QLabel(WelcomeBanner.TEXT)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.banner.setFont(font)
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setStyleSheet(f"color: {window.renderer.theme(PrimaryColour)}")
        self.project = PathLabel(window.project_dir.path)
        self.project.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project.setStyleSheet(f"color: {window.renderer.colour(MutedRole)}")
        self.rows = ConversationRows(window)
        layout = QVBoxLayout(self)
        layout.addSpacing(24)
        layout.addWidget(self.banner)
        layout.addWidget(self.project)
        layout.addSpacing(12)
        layout.addWidget(self.rows, 1)
        self.show_buses()

    def present(self, model: SidebarModel) -> None:
        self.rows.clear()
        for listing in self.listings:
            section = self.rows.section(listing.TITLE)
            listing.add(self.rows, section, model)
            section.setExpanded(True)
        self.show_buses()

    def present_failed(self, observed: FailedObservation) -> None:
        """The bus could not be read: say why, and keep the buses to switch to."""
        self.rows.clear()
        self.rows.section(f"Bus unavailable: {type(observed.error).__name__}: {observed.error}")
        self.show_buses()

    def show_buses(self) -> None:
        section = self.rows.section("Buses")
        for choice in BusChoice.held(time()):
            self.rows.add_row(section, BusRow(choice), "", choice.label(), "", choice.label())
        section.setExpanded(True)

    def resizeEvent(self, event) -> None:
        """The banner fills the width in whole characters, as the terminal draws it."""
        super().resizeEvent(event)
        font = self.banner.font()
        widest = max(WelcomeBanner.TEXT.splitlines(), key=len)
        advance = QFontMetricsF(font).horizontalAdvance(widest) / font.pointSizeF()
        font.setPointSizeF(max(4.0, (self.width() - 24) / advance))
        self.banner.setFont(font)

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        window.hide_sidebar()


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


class ConversationRows(TouchScrolled, QTreeWidget):
    """A tree of Toad's conversation rows in its sidebar tones: each row's unread badge and
    label with its summary under it in muted text; a tap activates the line."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.window = window
        self.setHeaderHidden(True)
        self.setIndentation(10)
        # Toad's sidebar tones: the sidebar's own, every other row one step off it.
        window.tone(self, QPalette.ColorRole.Base, SidebarToneColour)
        window.tone(self, QPalette.ColorRole.AlternateBase, AlternateRowToneColour)
        self.setAlternatingRowColors(True)
        self.setExpandsOnDoubleClick(False)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.itemClicked.connect(self.activate)

    def activate(self, item: SidebarItem) -> None:
        item.activate(self.window)

    def items(self):
        return (self.topLevelItem(index) for index in range(self.topLevelItemCount()))

    def section(self, title: str) -> SidebarSection:
        section = SidebarSection(title)
        section.setForeground(0, QColor(self.window.renderer.colour(MutedRole)))
        self.addTopLevelItem(section)
        return section

    def add_channel(self, parent: QTreeWidgetItem, name: str, channel) -> ConversationRow:
        return self.add_row(parent, ConversationRow(channel_target(name)),
                            channel.unread.badge, channel.label(), channel.summary(), channel.tooltip())

    def add_thread(self, parent: QTreeWidgetItem, name: str, thread) -> ConversationRow:
        return self.add_row(parent, ConversationRow(DirectTarget(name)),
                            thread.unread.badge, thread.label, thread.summary, thread.title)

    def add_row[Row: SidebarItem](self, parent: QTreeWidgetItem, row: Row, badge: str, label: str,
                                  summary: str, tooltip: str) -> Row:
        renderer = self.window.renderer
        text = QLabel(renderer.styled(f"{badge} " if badge else "", TextRole)
                      + renderer.styled(label, TextRole)
                      + (f"<br>{renderer.styled(summary, MutedRole)}" if summary else ""))
        text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.setContentsMargins(4, 4, 4, 4)
        row.setToolTip(0, tooltip)
        parent.addChild(row)
        row.setSizeHint(0, text.sizeHint())
        self.setItemWidget(row, 0, text)
        return row


class Sidebar(ConversationRows, SidebarSubscriber[Observing, FailedObservation]):
    """The bus's channels, each opening to the threads in it, and every thread, from the
    shared sidebar model; groups stay open or closed across updates."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self.observed: Observing | None = None
        self.expanded: set[str] = set()
        self.itemExpanded.connect(self.opened)
        self.itemCollapsed.connect(self.closed)

    def opened(self, item: SidebarItem) -> None:
        self.expanded.add(item.key)

    def closed(self, item: SidebarItem) -> None:
        self.expanded.discard(item.key)

    def bind_observation(self, observed: Observing) -> None:
        if self.observed is observed:
            return
        self.observed = observed
        observed.sidebar.channels.subscribe(self.rows_changed)
        observed.sidebar.threads.subscribe(self.rows_changed)
        self.window.coordination_access.show_sidebar(self, True)
        self.present()

    def rows_changed(self, changes: object) -> None:
        self.present()

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.observed = None
        self.clear()
        self.addTopLevelItem(SidebarSection(f"Bus unavailable: {type(observed.error).__name__}: {observed.error}"))
        self.window.workspace_sessions.home.present_failed(observed)

    def present(self, **changes: object) -> None:
        """Toad's sidebar rows: a badge and label, and the row's summary under it in
        muted text, from the shared row models."""
        if self.observed is None:
            return
        model: SidebarModel = self.observed.sidebar
        threads = model.threads.rows
        self.clear()
        for name, channel in model.channels.rows.items():
            group = self.add_channel(self.invisibleRootItem(), name, channel)
            for member in channel.members:
                self.add_thread(group, member, threads[member])
        everyone = self.section("Threads")
        for name, thread in threads.items():
            self.add_thread(everyone, name, thread)
        for item in self.items():
            item.setExpanded(item.key in self.expanded)
        self.window.workspace_sessions.home.present(model)
        self.window.paint_tabs()


class ActivityStrip(ObservedActivity, QtCoreObserver, QWidget):
    """Toad's activity sweep while the conversation's thread is working: the shared
    ACTIVITY_SWEEP ribbon sampled across the strip, each sample's two stops blended and
    drawn as tall as the ribbon is thick there."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.window = window
        self.row = ThreadStatusModel.pending("")
        self.is_mounted = False
        self.started = monotonic()
        self.setFixedHeight(6)
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / ACTIVITY_SWEEP.frames_per_second))
        self.timer.timeout.connect(self.update)

    @property
    def coordination(self) -> CoordinationAccess:
        return self.window.coordination_access

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.is_mounted:
            self.is_mounted = True
            self.start_observing()

    def show(self, row: ThreadStatusModel) -> None:
        self.row = row
        if self.working:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        if not self.working:
            return
        frame = ACTIVITY_SWEEP.frame(monotonic() - self.started)
        scheme = self.window.renderer.scheme
        width, height = self.width(), self.height()
        painter = QPainter(self)
        for x in range(width):
            start, end, amount, thickness = frame.sample((x + 0.5) / width)
            if thickness <= 0:
                continue
            ink = start.rgb(scheme).blend(end.rgb(scheme), amount)
            bar = max(1, round(height * thickness))
            painter.fillRect(x, (height - bar) // 2, 1, bar, QColor(ink.hex))
        painter.end()


class QtSessionEntry(SessionEntries):
    """The Qt window's entry family."""


class QtHistorySessionEntry(QtSessionEntry, HistorySessionEntry, shows=(CommsTab,)):
    """The shared conversation entry, drawn in this window's ConversationView."""

    def __call__(self, sessions: SessionNavigator) -> ConversationView:
        return ConversationView(sessions.app, self)


class PathLabel(QLabel):
    """A directory shown as Toad's info bar shows it: home-relative, then condensed from the
    middle out to the characters the label has room for. The full path is its tooltip."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.shown = home_relative(str(path), directory=True)
        self.setToolTip(str(path))
        self.setMinimumWidth(QFontMetricsF(self.font()).horizontalAdvance("~/…/"))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cells = int(self.width() / QFontMetricsF(self.font()).averageCharWidth())
        self.setText(condense_path(self.shown, max(1, cells)))


class ConversationView(Page, StatusOwner, SessionScope, QWidget):
    """One conversation tab: its newest page, read again whenever Core's stores change; the
    activity sweep and info row over its thread's status; and a sender."""

    page_size = 50

    def __init__(self, window: QtToadApp, entry: QtHistorySessionEntry) -> None:
        super().__init__()
        self.window, self.entry = window, entry
        self.content_ready = asyncio.Event()
        label = entry.unobserved_tab().label()
        self.messages = MessageView(window.renderer)
        self.thread_activity = ActivityStrip(window)
        self.label = QLabel(label)
        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status.setStyleSheet(f"color: {window.renderer.colour(MutedRole)}")
        self.directory = PathLabel(window.project_dir.path)
        self.directory.setStyleSheet(f"color: {window.renderer.colour(MutedRole)}")
        info = QHBoxLayout()
        info.setContentsMargins(6, 0, 6, 0)
        info.addWidget(self.directory, 1)
        info.addWidget(self.label)
        info.addWidget(self.status, 2)
        self.input = QLineEdit()
        self.input.setPlaceholderText(f"Message {label}")
        self.input.returnPressed.connect(self.send)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        footer = QHBoxLayout()
        footer.addWidget(self.input, 1)
        footer.addWidget(send)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.thread_activity)
        layout.addLayout(info)
        layout.addLayout(footer)

    @property
    def mode(self) -> str:
        return self.entry.mode

    @property
    def origin(self) -> SessionOrigin:
        """A conversation tab belongs to no session, so it has no session transcript."""
        return NoSessionOrigin(self.mode)

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        visited(self.entry.identity)
        self.reload()

    async def wait_content_ready(self) -> None:
        await self.content_ready.wait()

    def close_core_events(self) -> None:
        self.thread_activity.close_core_events()

    async def retire_presentation(self) -> None:
        """Qt keeps nothing drawn apart from the widgets, which go with the view."""

    @property
    def conversation(self) -> ConversationKind:
        return self.entry.key.conversation

    def reload(self) -> None:
        self.window.run_operation(ConversationRead, self.read_page)

    async def read_page(self) -> None:
        source = self.window.source()
        try:
            page: MessagePage = await asyncio.to_thread(
                self.conversation.page, source, PageBounds(limit=self.page_size))
            style = MarkdownMessageStyle()
            rows = (MessageRow(message, self.entry.viewer) for message in page.messages)
            self.messages.show_blocks(tuple(
                block for row in rows for block in (row.header, *style.body(row, row.text))))
        finally:
            self.content_ready.set()
        self.conversation.status_thread(source.root, self.window.coordination_access).refresh(self)
        self.label.setText(self.conversation.label(source.references()))
        read_only = await asyncio.to_thread(self.conversation.read_only, source.core)
        self.status.setText(await self.conversation.status_text(source, read_only=read_only))

    def send(self) -> None:
        body = self.input.text().strip()
        if not body:
            return
        self.input.clear()
        self.window.run_operation(MessageSend, partial(self.deliver, body))

    async def deliver(self, body: str) -> None:
        observed = self.window.coordination_access.observation.observed()
        await asyncio.to_thread(observed.send_user_message, self.conversation.send_target(), body)
        self.reload()


class QtWorkspaceViews(WorkspaceViews):
    """The Qt window's open views, stacked so the selected one shows; the home page stands
    in for a mode with no view here: the welcome page, or a saved tab this app has not
    opened."""

    def __init__(self, app: QtToadApp) -> None:
        self.app = app
        self.home = Welcome(app)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.home)
        self.views: dict[str, ConversationView] = {}

    @property
    def selected(self) -> Page:
        return self.pages.currentWidget()

    def require(self, identity: str) -> ConversationView:
        return self.views[identity]

    def origin(self, identity: str) -> SessionOrigin:
        if view := self.views.get(identity):
            return view.origin
        return NoSessionOrigin(identity)

    def navigation_owner(self) -> NoNavigationOwner:
        """Rows open from the sidebar through the shared history route; no view navigates."""
        return NoNavigationOwner(self.app)

    def prepare(self, mode: str) -> Page:
        if view := self.views.get(mode):
            return view
        sessions = self.app.session_navigation
        entry = sessions.get(mode)
        if entry is None:
            return self.home
        view = self.views[mode] = entry(sessions)
        self.pages.addWidget(view)
        return view

    def select(self, mode: str, visited: Callable[[CommsTab], object]) -> None:
        page = self.prepare(mode)
        self.pages.setCurrentWidget(page)
        page.shown(self.app, visited)

    def detach(self, identity: str) -> ConversationView | None:
        return self.views.pop(identity, None)

    async def finish(self, view: ConversationView) -> None:
        self.pages.removeWidget(view)
        view.deleteLater()


class QtToadApp(ClientApplication, QtCommsHost, QWidget):
    """The shared client application on Qt, over the Core a UI profile names: the threads,
    and a tab per open conversation; the bar under them is Toad's: the menu button, back
    and forward through the visit history, and the tabs."""

    session_entries = QtSessionEntry

    def __init__(self, connection: RemoteCoreConnection, project: Checkout,
                 preparation: PreparationRuntime, scheme: ColourScheme) -> None:
        super().__init__(project, preparation)
        self.initialize_client(NoAgent(), connection)
        self.setWindowTitle("Toad")
        self.renderer = QtLineRenderer(scheme)
        self.setPalette(self.palette_of(scheme))
        self.workspace_sessions = QtWorkspaceViews(self)
        self.sidebar = Sidebar(self)
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(self.workspace_sessions.pages)
        self.split.addWidget(self.sidebar)
        self.split.setStretchFactor(1, 2)
        self.sidebar_bar = QPushButton()
        self.sidebar_bar.setMinimumHeight(40)
        self.sidebar_bar.setFlat(True)
        self.sidebar_bar.clicked.connect(self.toggle_sidebar)
        self.menu = self.bar_button("☰", "Menu", self.show_menu)
        self.back = self.bar_button("←", "Back", partial(self.tab_order.navigate, -1))
        self.forward = self.bar_button("→", "Forward", partial(self.tab_order.navigate, 1))
        self.tabs = QTabBar()
        self.tabs.setStyleSheet("QTabBar::tab { min-height: 40px; padding: 0 14px; }")
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
        # The bar row is Toad's header band, in its header tone.
        chrome = QWidget()
        self.tone(chrome, QPalette.ColorRole.Window, HeaderToneColour)
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        chrome_layout.addWidget(self.sidebar_bar)
        chrome_layout.addLayout(bar)
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.addWidget(self.split, 1)
        layout.addWidget(chrome)
        # The welcome lists the channels and threads, so it starts with the sidebar down.
        self.hide_sidebar()
        self.changes = self.coordination_access.events.subscribe(CoordinationObserved, self.stores_changed)
        self.history = self.tab_order.events.subscribe(TabHistoryChanged, self.history_changed)
        self.history_changed()
        self.android_back = QShortcut(QKeySequence(Qt.Key.Key_Back), self, self.go_back,
                                      context=Qt.ShortcutContext.ApplicationShortcut)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.go_back,
                                context=Qt.ShortcutContext.ApplicationShortcut)
        self.winId()
        self.windowHandle().safeAreaMarginsChanged.connect(self.fit_safe_area)
        self.fit_safe_area(self.windowHandle().safeAreaMargins())

    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The profile a chosen bus names, read by the member this window launched with, so
        desktop keeps decoding in a process and Android in place."""
        return type(self.coordination_access.connection).startup(list(choice.arguments(())))

    async def open_saved_tabs(self) -> None:
        """The saved roster is read so tabs this app cannot draw yet stay saved; the sidebar
        and welcome bind the observation the connection serves."""
        await self.tab_order.load()
        self.coordination_access.open_current().show_sidebar(self.sidebar)

    def bar_button(self, text: str, tip: str, action) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setMinimumSize(48, 44)
        font = button.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        button.setFont(font)
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

    def tone(self, widget: QWidget, role: QPalette.ColorRole, member: type[ThemeColour]) -> None:
        """Paint a widget's palette role in one of Toad's theme tones."""
        palette = widget.palette()
        palette.setColor(role, QColor(self.renderer.theme(member)))
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)

    def fit_safe_area(self, margins: QMargins) -> None:
        """Keep every row clear of the status and navigation bars."""
        self.setContentsMargins(margins)

    def stores_changed(self, event: CoordinationObserved, subscription: object) -> None:
        self.workspace_sessions.selected.reload()

    def history_changed(self, *event: object) -> None:
        """Back and forward are live exactly when the visit history has a step that way."""
        self.back.setEnabled(self.tab_order.history_target(-1) is not None)
        self.forward.setEnabled(self.tab_order.history_target(1) is not None)

    def source(self) -> ObservedSource:
        observed = self.coordination_access.observation.observed()
        return ObservedSource(observed.core, observed.root, self.project_dir)

    # Tabs: SessionNavigation owns the open entries, TabOrder their order, the saved roster
    # and the visit history; the bar draws the shared tab projection.

    def paint_tabs(self) -> None:
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for tab in self.session_navigation.tabs:
            self.tabs.addTab(tab.label())
        self.tabs.blockSignals(False)
        self.mark_current()

    def mark_current(self) -> None:
        modes = [tab.mode_name for tab in self.session_navigation.tabs]
        mode = self.selected_mode
        self.tabs.setCurrentIndex(modes.index(mode) if mode in modes else -1)
        self.paint_sidebar_bar()

    # The sidebar sits behind a bar above the tabs, as on Toad's phone layout: ↑ brings it
    # up over the conversation, ↓ puts it back.

    def paint_sidebar_bar(self) -> None:
        index = self.tabs.currentIndex()
        title = self.tabs.tabText(index) if index >= 0 else "Channels"
        arrow = "↓" if self.sidebar.isVisible() else "↑"
        self.sidebar_bar.setText(f"{arrow}  {title}  {arrow}")

    def show_sidebar(self) -> None:
        self.sidebar.show()
        height = max(self.split.height(), 600)
        self.split.setSizes([height // 3, height - height // 3])
        self.paint_sidebar_bar()

    def hide_sidebar(self) -> None:
        self.sidebar.hide()
        self.paint_sidebar_bar()

    async def close_native_views(self) -> None:
        await self.session_navigation.close_views()

    async def close_rendering(self) -> None:
        await self.preparation.aclose()

    async def reveal_sidebar(self) -> bool:
        """The sidebar comes up over the conversation, as its bar would bring it."""
        self.show_sidebar()
        return True

    def toggle_sidebar(self) -> None:
        if self.sidebar.isVisible():
            self.hide_sidebar()
        else:
            self.show_sidebar()

    def show_menu(self) -> None:
        """Toad's application actions under their labels, as its menu lists them; a choice
        runs as its own operation. popup(), not exec(): exec's nested event loop under qasync
        showed nothing on Android."""
        self.menu_popup = QMenu(self)
        for command, label in ApplicationAction.menu(self):
            self.menu_popup.addAction(label, partial(self.run_operation, MenuActionRun, partial(command.apply, self)))
        corner = self.menu.mapToGlobal(self.menu.rect().topLeft())
        self.menu_popup.popup(corner - QPoint(0, self.menu_popup.sizeHint().height()))

    def open_row(self, row: ConversationRow) -> None:
        self.run_operation(ConversationOpen, partial(self.open_route, row.target))

    async def open_route(self, route: HistoryRouted) -> None:
        await self.session_navigation.history(project_path=self.project_dir, route=route)
        self.hide_sidebar()

    @property
    def selected_mode(self) -> str:
        return self.workspace_sessions.selected.mode

    def switch(self, mode: str, visited: Callable[[CommsTab], object]) -> None:
        self.workspace_sessions.select(mode, visited)
        self.mark_current()

    async def select_session(self, mode: str) -> None:
        """A person's selection: its visit is recorded as its tab is shown."""
        self.switch(mode, self.tab_order.record_visit)

    def show_history_step(self, mode: str) -> asyncio.Task[None]:
        """A history step, whose visit TabOrder recorded when it took the step. TabOrder
        does not wait on the switch, so it runs as its own task, as Textual's does."""
        return asyncio.ensure_future(self.step_to(mode))

    async def step_to(self, mode: str) -> None:
        self.switch(mode, lambda identity: None)

    def update_show_sessions(self) -> None:
        """The open tabs changed: the bar draws them again."""
        self.paint_tabs()

    def visit_index(self, index: int) -> None:
        self.switch(self.session_navigation.tabs[index].mode_name, self.tab_order.record_visit)

    def close_index(self, index: int) -> None:
        self.run_operation(TabClose, partial(self.session_navigation.close,
                                             self.session_navigation.tabs[index].mode_name))

    def go_back(self) -> None:
        """Android back: an open sidebar goes down first; then the visit history's previous
        tab; with none, the sidebar comes up; with it up and nothing behind, the app closes,
        as back does at an app's first screen."""
        if self.sidebar.isVisible() and self.workspace_sessions.views:
            self.hide_sidebar()
        elif self.tab_order.history_target(-1) is not None:
            self.tab_order.navigate(-1)
        elif not self.sidebar.isVisible():
            self.show_sidebar()
        else:
            self.close()
