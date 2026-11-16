"""The Qt application: the shared client application drawn as Toad's tabs over the
conversations you open, and its sidebar of channels and threads behind the bar above them.

Tabs open, switch and close through the shared SessionNavigation, as Textual's do: a
sidebar row is the shared history route, each tab is the shared conversation entry, and
QtWorkspaceViews draws its view, a Qt ConversationView.
"""

from __future__ import annotations

import asyncio
from time import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import ClassVar, Self
from functools import partial
from pathlib import Path

from agent_comms.messaging.message_reference import MessageReference
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transport.request import CoreAccess
from agent_comms.ui_model.sidebar import SidebarModel
from formbridge.operations import ExclusiveKind, OperationKind
from PySide6.QtCore import QEvent, QMargins, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.services.application_shortcuts import ShortcutLifecycle
from pyqt_reactive.widgets.elided_line import ElidedLine
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from ui_theme.scheme import ColourScheme, PrimaryColour

from toad.client.application import ClientApplication
from toad.client.application_actions import ApplicationAction
from toad.client.bus_selection import (
    BusChoice,
    BusListing,
    BusPickerHost,
    PickerRow,
    TailnetAnswer,
)
from toad.client.offered_action import OfferedAction
from toad.client.bus_submission import BusSubmissions, SubmissionView, TypedText
from toad.client.connection import (
    CoreConnection,
    FailedObservation,
    Observing,
    RemoteCoreConnection,
)
from toad.client.conversation import ConversationKind
from toad.client.conversation_capabilities import ConversationSource
from toad.client.history import ChannelDestination, WireSource, WireView
from toad.client.history_entry import HistorySessionEntry
from toad.client.history_notifications import HistoryNotifications
from toad.application_lifetime import ApplicationStart
from toad.client.condensed_path import condense_path, home_relative
from toad.client.platform import host
from toad.client.line_blocks import MutedRole
from toad.client.welcome import ChannelListing, ThreadListing, WelcomeBanner
from toad.client.referenced_core import ReferencedCore
from toad.client.submission import MessageDestination
from toad.client.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.client.subscribers import SidebarSubscriber
from toad.client.tab_identity.kinds import CommsTab
from toad.command_catalog import CommandCatalog
from toad.constants import WELCOME
from toad.core.events import CoordinationObserved, TabHistoryChanged
from toad.message_rows import MarkdownMessageStyle
from toad.launch_binding import NoAgent
from toad.navigation_context import NoNavigationOwner
from toad.navigation_target import DirectTarget, HistoryRouted, channel_target
from toad.qt.activity import ChannelActivity, PeerActivity
from toad.qt.composer import ChannelComposer, Composer, ComposerHost, MessageComposer
from toad.qt.host import QtCommsHost
from toad.qt.history import NoTask, QtConversationHistory, QtHistoryWindow, QtWireFragment
from toad.qt.lines import QtLineRenderer
from toad.session_host import SessionEntries, SessionNavigator, WorkspaceViews
from toad.status_thread import StatusOwner
from toad.target_commands import TargetContext
from toad.work_preparation import PreparationRuntime


class ConversationOpen(OperationKind, ExclusiveKind):
    """Opens a tapped row's conversation in its tab; a newer tap supersedes the running one."""


class MessageSend(OperationKind):
    """Sends one message; sends run side by side and are never superseded."""


class CommandRead(OperationKind, ExclusiveKind):
    """Reads the conversation's command catalog for its composer; a newer read supersedes it."""


class MenuActionRun(OperationKind):
    """One application action chosen from the menu."""


class TabClose(OperationKind):
    """Closes one tab; closes run side by side."""


class TabMove(OperationKind):
    """Moves one dragged tab in the shared tab order; moves run in the order dragged."""


@dataclass(frozen=True)
class ApplicationKeys:
    """The keys the Qt window answers anywhere: Android's back key and Escape both go back."""

    android_back: str = "Back"
    escape: str = "Esc"


@dataclass(frozen=True)
class ObservedSource(ConversationSource):
    """The observed Core's reads, in the project this window views."""

    core: CoreAccess
    root: Path
    project: Checkout


class SidebarItem(QTreeWidgetItem):
    """One line of the sidebar tree; its row widget draws it, a tap activates it."""

    key: str
    drawn: tuple[str, str, str, str] = ("", "", "", "")

    def draw(self, badge: str, label: str, summary: str, tooltip: str) -> None:
        """Draw this line's text; a line whose text is unchanged is left alone."""
        text = (badge, label, summary, tooltip)
        if text == self.drawn:
            return
        self.drawn = text
        self.setData(0, LAYOUT_ROLE, StyledTextLayout(
            name=Segment(label), status_prefix=f"{badge} " if badge else "", detail_line=summary,
            multiline=True))
        self.setToolTip(0, tooltip)

    def placed(self) -> None:
        """A new line needs nothing once it is in the tree."""

    def subtree(self) -> Iterator[SidebarItem]:
        """This line and every line under it."""
        yield self
        for index in range(self.childCount()):
            yield from self.child(index).subtree()

    def activate(self, window: QtToadApp) -> None:
        """A group line opens and closes its group."""
        self.setExpanded(not self.isExpanded())

    def held_actions(self, listing: Welcome) -> tuple[OfferedAction, ...]:
        """What holding a finger on this line, or right-clicking it, offers: nothing, for
        most lines."""
        return ()


class SidebarSection(SidebarItem):
    """A group of rows with a title, such as Threads."""

    def __init__(self, title: str) -> None:
        super().__init__([title])
        self.key = title


class OpenSection(SidebarSection):
    """A section that starts open, as the welcome's do; a tap still closes it."""

    def placed(self) -> None:
        self.setExpanded(True)


class UnavailableSection(SidebarSection):
    """The line saying why the bus could not be read."""

    def __init__(self, observed: FailedObservation) -> None:
        super().__init__(f"Bus unavailable: {type(observed.error).__name__}: {observed.error}")


class ConversationRow(SidebarItem):
    """A row that opens its conversation through the shared history route it holds."""

    def __init__(self, target: HistoryRouted) -> None:
        super().__init__()
        self.key = target.name
        self.target = target

    @classmethod
    def channel(cls, name: str, channel) -> ConversationRow:
        row = cls(channel_target(name))
        row.draw(channel.unread.badge, channel.label(), channel.summary(), channel.tooltip())
        return row

    @classmethod
    def thread(cls, name: str, thread) -> ConversationRow:
        row = cls(DirectTarget(name))
        row.draw(thread.unread.badge, thread.label, thread.summary, thread.title)
        return row

    def activate(self, window: QtToadApp) -> None:
        window.open_row(self)


class BusRow(SidebarItem):
    """A bus the welcome lists; a tap does what picking that row in the Textual picker does:
    switch onto a held bus, or ask a tailnet peer for a profile to its bus."""

    def __init__(self, choice: PickerRow) -> None:
        super().__init__()
        self.key = choice.label()
        self.choice = choice
        self.draw("", choice.label(), "", choice.label())

    def activate(self, window: QtToadApp) -> None:
        self.choice.chosen(window)

    def held_actions(self, listing: Welcome) -> tuple[OfferedAction, ...]:
        """The bus row's own (PickerRow.held_actions): forgetting a saved one."""
        return self.choice.held_actions(listing)


class Page:
    """A page of the window: shown when selected, read again when Core's stores change."""

    mode: str

    def reload(self) -> None:
        """A page fed by its own subscription has nothing to read again."""

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        """Selected: read again; a tab passes its identity to the visit history."""
        self.reload()


class QtChannelListing(ChannelListing):
    def keep(self, lines: KeptLines, model: SidebarModel) -> None:
        for name in self.listed(model):
            lines.keep(ConversationRow.channel(name, model.channels.rows[name]))


class QtThreadListing(ThreadListing):
    def keep(self, lines: KeptLines, model: SidebarModel) -> None:
        for name in self.listed(model):
            lines.keep(ConversationRow.thread(name, model.threads.rows[name]))


class WelcomeContent:
    """What the welcome lists above its buses: nothing until the bus answers."""

    def draw(self, top: KeptLines) -> None:
        pass


@dataclass(frozen=True)
class ListedModel(WelcomeContent):
    """The channels and threads the shared welcome lists."""

    model: SidebarModel
    listings: ClassVar[tuple[QtChannelListing | QtThreadListing, ...]] = (QtChannelListing(), QtThreadListing())

    def draw(self, top: KeptLines) -> None:
        for listing in self.listings:
            with top.group(OpenSection(listing.TITLE)) as lines:
                listing.keep(lines, self.model)


@dataclass(frozen=True)
class ListedFailure(WelcomeContent):
    """The bus could not be read: say why."""

    observed: FailedObservation

    def draw(self, top: KeptLines) -> None:
        top.keep(UnavailableSection(self.observed))


class Banner(QWidget):
    """Toad's banner, filling the width it is given in whole characters, as the terminal
    draws it: each character in its own cell of the grid. Android's monospace font has no
    box-drawing glyphs, and the fallback's glyphs are wider, so text drawn as a run slid
    every row off the blocks above it. It takes the width and never asks for one."""

    LINES = WelcomeBanner.TEXT.splitlines()
    COLUMNS = max(map(len, LINES))

    def __init__(self, colour: str) -> None:
        super().__init__()
        self.colour = QColor(colour)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(font)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def cell(self) -> float:
        return self.contentsRect().width() / self.COLUMNS

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        font = self.font()
        advance = QFontMetricsF(font).horizontalAdvance("\u2588") / font.pointSizeF()
        font.setPointSizeF(max(4.0, self.cell() / advance))
        self.setFont(font)
        self.setFixedHeight(round(len(self.LINES) * QFontMetricsF(font).height()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.colour)
        metrics = QFontMetricsF(self.font())
        cell, left, top = self.cell(), self.contentsRect().left(), self.contentsRect().top()
        for row, line in enumerate(self.LINES):
            baseline = top + row * metrics.height() + metrics.ascent()
            for column, character in enumerate(line):
                if not character.isspace():
                    painter.drawText(QPointF(left + column * cell, baseline), character)


class BusAddress(QLineEdit):
    """Where a reader types a machine to add by hand, under the welcome's Buses: the Textual
    picker's field, asked through the same BusPickerHost.ask_typed_host."""

    def __init__(self, host: BusPickerHost) -> None:
        super().__init__(placeholderText="Add a machine by name or address")
        self.host = host
        self.returnPressed.connect(self.ask)

    def ask(self) -> None:
        self.host.ask_typed_host(self.text())
        self.clear()


class SwallowsRelease(QObject):
    """Eats the one release that ends a held finger, then goes: the finger was holding the
    row for its actions, so letting go must not also tap it and open that bus."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            watched.removeEventFilter(self)
            self.deleteLater()
            return True
        return False


class HeldRowMenu(QObject):
    """A tree line's held actions (SidebarItem.held_actions), offered where a finger is held
    on it or a mouse right-clicks it (a phone has no right button), in the window's own
    panel, as its menu is (QtToadApp.offer)."""

    def __init__(self, listing: Welcome) -> None:
        super().__init__(listing)
        self.listing = listing
        rows = listing.rows
        rows.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        rows.customContextMenuRequested.connect(self.offer)
        rows.viewport().grabGesture(Qt.GestureType.TapAndHoldGesture)
        rows.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Gesture:
            held = event.gesture(Qt.GestureType.TapAndHoldGesture)
            if held is not None and held.state() == Qt.GestureState.GestureFinished:
                viewport = self.listing.rows.viewport()
                viewport.installEventFilter(SwallowsRelease(viewport))
                self.offer(viewport.mapFromGlobal(held.position().toPoint()))
                return True
        return False

    def offer(self, point: QPoint) -> None:
        """``point`` is in the tree's viewport, where QAbstractScrollArea reports it."""
        rows = self.listing.rows
        item: SidebarItem | None = rows.itemAt(point)
        if item is None:
            return
        actions = item.held_actions(self.listing)
        if actions:
            self.listing.host.offer(actions)


class Welcome(Page, BusListing, QWidget):
    """Toad's welcome, while no conversation tab is open and in place of a saved tab this app
    has not opened: the banner, the project, the channels and threads the shared welcome
    lists, and the buses (BusListing): the remote ones this machine holds, with the peers
    the tailnet reports holding one, a field to add a machine by name or address, and a held
    finger on a saved one to forget it. A Qt client is always remote, so this machine's own
    bus is not listed."""

    mode = WELCOME
    BUSES = "Buses"

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.host = window
        self.banner = Banner(window.renderer.theme(PrimaryColour))
        self.project = PathLabel(window.project_dir.path)
        self.project.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project.setStyleSheet(f"color: {window.renderer.colour(MutedRole)}")
        self.rows = ConversationRows(window)
        self.held_menu = HeldRowMenu(self)
        self.address = BusAddress(window)
        layout = QVBoxLayout(self)
        layout.addSpacing(24)
        layout.addWidget(self.banner)
        layout.addWidget(self.project)
        layout.addSpacing(12)
        layout.addWidget(self.rows, 1)
        layout.addWidget(self.address)
        self.content: WelcomeContent = WelcomeContent()
        self.relist()

    def picker_host(self) -> BusPickerHost:
        return self.host

    def held_rows(self) -> tuple[PickerRow, ...]:
        return BusChoice.held(time())

    def say_failure(self, reason: str) -> None:
        self.host.show_warning(reason, "Tailnet buses")

    def present(self, model: SidebarModel) -> None:
        self.content = ListedModel(model)
        self.relist()

    def present_failed(self, observed: FailedObservation) -> None:
        """The bus could not be read: say why, and keep the buses to switch to."""
        self.content = ListedFailure(observed)
        self.relist()

    def show_rows(self, rows: tuple[PickerRow, ...]) -> None:
        """What the welcome lists, then the Buses section with ``rows``: a tailnet answer
        arrives between sidebar updates, and both redraw the same lines in place."""
        self.rows.redraw(partial(self.draw_lines, rows))

    def draw_lines(self, buses: tuple[PickerRow, ...], top: KeptLines) -> None:
        self.content.draw(top)
        with top.group(OpenSection(self.BUSES)) as section:
            for choice in buses:
                section.keep(BusRow(choice))

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        window.hide_sidebar()


class KeptLines:
    """One tree line's children through one redraw, by kind and key. A line still wanted
    keeps its item, so a press on it and its open or closed group survive the update; the
    lines no longer wanted go at the end. One redraw visits each line once."""

    def __init__(self, parent: QTreeWidgetItem) -> None:
        self.parent = parent
        self.previous = {(type(line), line.key): line
                         for line in (parent.child(index) for index in range(parent.childCount()))}
        self.count = 0

    def keep[Row: SidebarItem](self, line: Row) -> Row:
        kept = self.previous.pop((type(line), line.key), line)
        kept.draw(*line.drawn)
        if kept is line:
            self.parent.insertChild(self.count, line)
            line.placed()
        elif self.parent.child(self.count) is not kept:
            # The view holds which groups are open; a taken item forgets, so a moved line
            # opens its groups again where it lands.
            opened = [group for group in kept.subtree() if group.isExpanded()]
            self.parent.takeChild(self.parent.indexOfChild(kept))
            self.parent.insertChild(self.count, kept)
            for group in opened:
                group.setExpanded(True)
        self.count += 1
        return kept

    def group(self, line: SidebarItem) -> KeptLines:
        """``line`` kept, with its own children kept in turn until the group closes."""
        return KeptLines(self.keep(line))

    def close(self) -> None:
        for _ in range(self.parent.childCount() - self.count):
            self.parent.takeChild(self.count)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *raised: object) -> None:
        self.close()


class ConversationRows(TouchScrolled, QTreeWidget):
    """A tree of Toad's conversation rows in the theme's sidebar tones, every other row a
    step off: pyqt-reactive's preview delegate paints each row's unread badge and label with
    its summary under it in muted text; a tap activates the line."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.window = window
        scheme = window.theme.color_scheme
        self.setHeaderHidden(True)
        self.setIndentation(10)
        self.setStyleSheet(scheme.styles.generate_tree_widget_style())
        self.setItemDelegate(MultilinePreviewItemDelegate(
            scheme.to_qcolor(scheme.text_primary), scheme.to_qcolor(scheme.text_secondary),
            scheme.to_qcolor(scheme.selection_text), self))
        self.setAlternatingRowColors(True)
        self.setExpandsOnDoubleClick(False)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.itemClicked.connect(self.activate)

    def activate(self, item: SidebarItem) -> None:
        item.activate(self.window)

    def items(self):
        return (self.topLevelItem(index) for index in range(self.topLevelItemCount()))

    def redraw(self, draw: Callable[[KeptLines], object]) -> None:
        """Draw every line again in place, by kind and key: a line still wanted keeps its
        item, so a finger on it still lands and a group keeps its open or closed state; a
        line no longer wanted goes. Rows change in place; nothing is cleared and rebuilt."""
        with KeptLines(self.invisibleRootItem()) as top:
            draw(top)


class Sidebar(ConversationRows, SidebarSubscriber[Observing, FailedObservation]):
    """The bus's channels, each opening to the threads in it, and every thread, from the
    shared sidebar model. It only draws: the coordination access binds it to each current
    observation, and its lines are kept in place across updates, so groups stay open or
    closed and a press stays on its row."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self.observed: Observing | None = None

    def bind_observation(self, observed: Observing) -> None:
        if self.observed is observed:
            return
        self.observed = observed
        observed.sidebar.channels.subscribe(self.rows_changed)
        observed.sidebar.threads.subscribe(self.rows_changed)
        self.present()

    def rows_changed(self, changes: object) -> None:
        self.present()

    def draw_lines(self, model: SidebarModel, top: KeptLines) -> None:
        threads = model.threads.rows
        for name, channel in model.channels.rows.items():
            with top.group(ConversationRow.channel(name, channel)) as group:
                for member in channel.members:
                    group.keep(ConversationRow.thread(member, threads[member]))
        with top.group(SidebarSection("Threads")) as everyone:
            for name, thread in threads.items():
                everyone.keep(ConversationRow.thread(name, thread))

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        self.observed = None
        self.redraw(lambda top: top.keep(UnavailableSection(observed)))
        self.window.workspace_sessions.home.present_failed(observed)

    def present(self, **changes: object) -> None:
        """Toad's sidebar rows: a badge and label, and the row's summary under it in
        muted text, from the shared row models."""
        if self.observed is None:
            return
        model: SidebarModel = self.observed.sidebar
        self.redraw(partial(self.draw_lines, model))
        self.window.workspace_sessions.home.present(model)
        self.window.paint_tabs()


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


class ConversationView(Page, StatusOwner, SessionScope, SubmissionView, WireView, HistoryNotifications,
                       ComposerHost, QWidget):
    """One conversation tab: its history, paged lazily by the pager Textual's channels use
    and drawn as virtual rows, read again whenever Core's stores change; the info row over
    its thread's status; and the composer and activity its kind chooses, sending through
    the shared submissions as Textual's conversation view does."""

    def __init__(self, app: QtToadApp, entry: QtHistorySessionEntry) -> None:
        super().__init__()
        self.app, self.entry = app, entry
        self.submissions = BusSubmissions(self)
        self.content_ready = asyncio.Event()
        self.notification_work: asyncio.Task | NoTask = NoTask()
        label = entry.unobserved_tab().label()
        self.messages = QtHistoryWindow(app.renderer.scheme)
        self.message_history = QtConversationHistory(self.messages, self, app)
        source = app.source()
        self.message_history.initialize_source(WireSource(
            source.root, self.conversation, source.project, entry.viewer, MarkdownMessageStyle(),
            access=app.coordination_access, core=source.core, fragments=QtWireFragment))
        self.message_history.observe_source()
        self.label = ElidedLine(label)
        self.status = ElidedLine()
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status.setStyleSheet(f"color: {app.renderer.colour(MutedRole)}")
        self.directory = PathLabel(app.project_dir.path)
        self.directory.setStyleSheet(f"color: {app.renderer.colour(MutedRole)}")
        info = QHBoxLayout()
        info.setContentsMargins(6, 0, 6, 0)
        info.addWidget(self.directory, 1)
        info.addWidget(self.label)
        info.addWidget(self.status, 2)
        self.composer = self.conversation.prompt(self)
        self.composer.labelled(label)
        self.activity = tuple(self.conversation.compose_activity(self))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.messages, 1)
        layout.addLayout(info)
        layout.addWidget(self.composer)
        for line in self.activity:
            layout.addWidget(line)

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

    def shows(self, root: str | Path, conversation: ConversationKind) -> bool:
        """Whether this tab is still open on this conversation, read from this root."""
        return (self.app.workspace_sessions.views.get(self.mode) is self and conversation == self.conversation
                and Path(root) == Path(self.app.source().root))

    # Core's notification answers for the messages this tab shows

    def notification_targets(self) -> tuple[QtConversationHistory, ...]:
        return (self.message_history,)

    @property
    def can_draw_on_screen(self) -> bool:
        return self.message_history.can_draw_on_screen

    @property
    def notification_root(self) -> str:
        return str(self.app.source().root)

    def report_queue_evidence(self) -> None:
        """Qt shows no queue evidence beside the conversation."""

    def run_notification_work(self, work: Awaitable[None]) -> None:
        self.notification_work.cancel()
        self.notification_work = asyncio.ensure_future(work)

    def check_notifications_after_refresh(self) -> None:
        QTimer.singleShot(0, self.check_notifications)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self.check_notifications)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        super().hideEvent(event)
        self.app.coordination_access.stop_notifications(self)

    async def wait_content_ready(self) -> None:
        await self.content_ready.wait()

    def close_core_events(self) -> None:
        for line in self.activity:
            line.close_activity()
        self.composer.receipt.stop()
        self.app.coordination_access.stop_notifications(self)
        self.message_history.retire_source()

    async def retire_presentation(self) -> None:
        """The history lets go of its page reader; its rows go with the widgets."""
        self.message_history.close()

    @property
    def conversation(self) -> ConversationKind:
        return self.entry.key.conversation

    def reload(self) -> None:
        self.message_history.page_source.schedule_refresh(self)

    async def _refresh(self):
        return self.message_history.page_source.schedule_refresh(self)

    async def show_sent(self, sent: MessageReference) -> None:
        """Follow the conversation's end and read it now; the queue entry retires once `sent` is drawn."""
        self.messages.jump_to_latest()
        await self._refresh()

    def dispatch_sync(self, event: object) -> None:
        """Qt reads its label from the source's references on every refresh."""

    async def _refresh_source(self) -> None:
        """Read what changed in the conversation and draw it, then the status beside it."""
        history = self.message_history
        source = self.app.source()
        try:
            await history.read_changes()
        finally:
            self.content_ready.set()
        self.submissions.settle()
        self.composer.receipt.follow(str(source.root), next((
            references for fragment in reversed(history.fragments) if (references := fragment.sent_references)), ()),
            history.pages[-1].prepared.page.source.selection.notification_identity)
        self.conversation.status_thread(source.root, self.app.coordination_access).refresh(self)
        label = self.conversation.label(source.references())
        self.label.setText(label)
        self.composer.labelled(label)
        read_only = await asyncio.to_thread(self.conversation.read_only, source.core)
        await self.refresh_composer(read_only)
        self.status.setText(await self.conversation.status_text(source, read_only=read_only))
        await self.conversation.update_mentions(self, source)

    # The kind's composer and activity (ConversationActivity)

    def channel_prompt(self, placeholder: str) -> ChannelComposer:
        return ChannelComposer(self, self.app.renderer, placeholder)

    def message_prompt(self) -> MessageComposer:
        return MessageComposer(self, self.app.renderer)

    def compose_channel_activity(self) -> Iterator[ChannelActivity]:
        yield ChannelActivity(self.app, self.app.renderer, self.conversation)

    def compose_peer_activity(self, peer: ThreadIncarnation) -> Iterator[PeerActivity]:
        self.thread_activity = PeerActivity(self.app, self.app.renderer, peer)
        yield self.thread_activity

    async def update_channel_mentions(self, source: ReferencedCore) -> None:
        answer = await self.app.coordination_access.current_sidebar()
        self.composer.set_mention_candidates(
            await self.app.preparation.run_thread(self.conversation.mention_candidates, answer))

    # Commands the composer offers after a /

    async def command_target_context(self) -> TargetContext:
        source = self.app.source()
        return TargetContext.in_conversation(
            self.app, source.root, self.conversation, self.entry.viewer, source.project, self.mode)

    async def read_command_catalog(self) -> CommandCatalog:
        return await CommandCatalog.read(self.app, (), self.command_target_context())

    def load_commands(self, composer: Composer) -> None:
        self.app.run_operation(CommandRead, self.read_commands)

    async def read_commands(self) -> None:
        self.composer.set_commands((await self.read_command_catalog()).commands)

    # Sending, through the shared submissions (SubmissionView)

    def submit(self, text: TypedText) -> None:
        self.app.run_operation(MessageSend, partial(self.start_send, text))

    async def start_send(self, text: TypedText) -> None:
        if text.text.startswith("/") and (await self.read_command_catalog()).recognizes(text.text):
            self.delivery_refused(f"{text.text.partition(' ')[0]} is a command, and this client runs no commands",
                                  text.source_text)
            return
        root = self.app.source().root
        await self.submissions.start_bus(text, ChannelDestination(root, self.conversation, self)).prepare()

    def delivery_refused(self, description: str, body: str) -> None:
        self.composer.restore_draft(body)
        self.composer.show_failure(self.refusal_notice(description))

    def delivery_unknown(self, description: str, body: str) -> None:
        self.composer.restore_draft(body)
        self.composer.show_failure(self.unknown_notice(description))

    async def refresh_composer(self, read_only: bool) -> None:
        self.composer.hold(MessageDestination.read_only_reason if read_only else "")

    def draws_user_message(self, reference: MessageReference) -> bool:
        return self.message_history.draws(reference)

    def record_input(self, text: str) -> None:
        """The Qt composer recalls no earlier input, so there is no history to keep."""

    def run_submission(self, send: Callable[[], Awaitable[None]]) -> None:
        self.app.run_operation(MessageSend, send)

    def submissions_changed(self) -> None:
        self.composer.show_submitting()


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


class QtToadApp(ClientApplication, QtCommsHost, QWidget, metaclass=PyQtWidgetMeta):
    """The shared client application on Qt, over the Core a UI profile names: the threads,
    and a tab per open conversation; the bar under them is Toad's: the menu button, back
    and forward through the visit history, and the tabs."""

    session_entries = QtSessionEntry

    def __init__(self, connection: RemoteCoreConnection, project: Checkout,
                 preparation: PreparationRuntime, scheme: ColourScheme) -> None:
        super().__init__(project, preparation, scheme)
        self.initialize_client(NoAgent(), connection)
        self.setWindowTitle("Toad")
        self.renderer = QtLineRenderer(scheme)
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
        # ≡ is in Android's Noto Sans Math; ☰ is in no font Android ships, so it drew a box.
        self.menu = self.bar_button("≡", "Menu", self.show_menu)
        self.back = self.bar_button("←", "Back", partial(self.tab_order.navigate, -1))
        self.forward = self.bar_button("→", "Forward", partial(self.tab_order.navigate, 1))
        # pyqt-reactive's tab bar in the theme's tab style; a dragged tab moves in the
        # shared tab order, which the bar then draws again.
        self.tabs = TearOffTabBar()
        self.tabs.setStyleSheet(self.theme.color_scheme.styles.generate_tab_widget_style())
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBarClicked.connect(self.visit_index)
        self.tabs.tabCloseRequested.connect(self.close_index)
        self.tabs.tabMoved.connect(self.move_index)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        for widget in (self.menu, self.back, self.forward):
            bar.addWidget(widget)
        bar.addWidget(self.tabs, 1)
        # The bar row is Toad's header band: a frame in the theme's header tone, with the
        # latest notice over it.
        chrome = QFrame()
        chrome.setStyleSheet(self.theme.color_scheme.styles.generate_frame_style())
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        chrome_layout.addWidget(self.status_line)
        self.menu_panel = QWidget()
        QVBoxLayout(self.menu_panel).setContentsMargins(8, 4, 8, 4)
        self.menu_panel.hide()
        chrome_layout.addWidget(self.menu_panel)
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
        self.shortcuts = ShortcutLifecycle[ApplicationKeys](QApplication.instance())
        self.shortcuts.bind_command(lambda keys: keys.android_back, "Back", self.go_back)
        self.shortcuts.bind_command(lambda keys: keys.escape, "Back", self.go_back)
        self.shortcuts.apply(ApplicationKeys())
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
        await self.coordination_access.follow_sidebar(self.sidebar)

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

    def begin_frontend(self) -> None:
        """The window opens as the platform opens windows, then the saved tabs, as the start
        a bus switch waits for."""
        host.open_window(self)
        self.run_operation(ApplicationStart, self.open_saved_tabs)

    def tailnet_answered(self, answer: TailnetAnswer) -> None:
        """The welcome is this window's one bus listing."""
        answer.shown_in(self.workspace_sessions.home)

    async def close_native_views(self) -> None:
        self.shortcuts.close()
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
        """Toad's application actions under their labels, as its menu lists them, in a panel
        over the bar; a choice runs as its own operation and closes the panel. The panel
        is part of this window: a QMenu is a second native window, and opening one killed
        the app on Android with no Python error."""
        if self.menu_panel.isVisible():
            self.menu_panel.hide()
            return
        self.offer(tuple(
            OfferedAction(label, partial(self.run_operation, MenuActionRun, partial(command.apply, self)))
            for command, label in ApplicationAction.menu(self)))

    def offer(self, actions: tuple[OfferedAction, ...]) -> None:
        """``actions`` as buttons in the panel over the bar, in place of what it showed; a
        choice closes the panel and runs. The menu and a held bus row both offer here."""
        layout = self.menu_panel.layout()
        while layout.count():
            layout.takeAt(0).widget().deleteLater()
        for action in actions:
            choice = QPushButton(action.label)
            choice.setFlat(True)
            choice.setMinimumHeight(44)
            choice.clicked.connect(partial(self.choose_offered, action))
            layout.addWidget(choice)
        self.menu_panel.show()

    def choose_offered(self, action: OfferedAction) -> None:
        self.menu_panel.hide()
        action.run()

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

    def move_index(self, start: int, end: int) -> None:
        """A tab dragged from one place in the bar to another: it moves past the tab it
        displaced in the shared order, which also holds saved tabs this window has not
        opened, and the bar draws that order again."""
        tabs, order = self.session_navigation.tabs, self.tab_order.names
        moved, displaced = tabs[start].identity, tabs[end].identity
        self.run_operation(TabMove, partial(self.move_tab, moved, order.index(displaced) - order.index(moved)))

    async def move_tab(self, identity: CommsTab, steps: int) -> None:
        await self.tab_order.move(identity, steps)
        self.paint_tabs()

    def go_back(self) -> None:
        """Android back: an open sidebar goes down first; then the visit history's previous
        tab; with none, the sidebar comes up; with it up and nothing behind, the app closes,
        as back does at an app's first screen. An open menu closes before any of that."""
        if self.menu_panel.isVisible():
            self.menu_panel.hide()
        elif self.sidebar.isVisible() and self.workspace_sessions.views:
            self.hide_sidebar()
        elif self.tab_order.history_target(-1) is not None:
            self.tab_order.navigate(-1)
        elif not self.sidebar.isVisible():
            self.show_sidebar()
        else:
            self.close()
