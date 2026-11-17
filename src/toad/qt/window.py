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
from agent_comms.ui_model.message_category import all_categories
from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel
from formbridge.operations import ExclusiveKind, OperationKind
from PySide6.QtCore import QEvent, QMargins, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming import StatusColorRole
from pyqt_reactive.services.application_shortcuts import ShortcutLifecycle
from pyqt_reactive.widgets.fitted_text import ElidedLine
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from pyqt_reactive.widgets.shared.tear_off_tab_widget import TearOffTabBar
from pyqt_reactive.widgets.shared.touch_scrolled import TouchScrolled
from ui_theme.scheme import ColourScheme, PrimaryColour

from toad.app_core import CorePrewarm
from toad.client.application import ClientApplication
from toad.qt.workspace_frame import QtWorkspaceFrame
from toad.flash_host import FlashHost
from toad.widget_view import WorkspaceHosted
from toad.workspace_frame import WorkspaceFrame
from toad.client.application_actions import ApplicationAction, NewSessionAction
from toad.client.bus_connect import BusConnectDecision
from toad.client.bus_selection import (
    BusChoice,
    BusListing,
    BusPickerHost,
    PickerRow,
    TailnetAnswer,
)
from toad.client.offered_action import OfferedAction
from toad.client.bus_submission import BusSubmissions, SubmissionView, TypedText
from toad.submission_queue import NoQueueSource, QueueSource
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
from toad.client.platform import host
from toad.client.line_blocks import LineLink, MutedRole
from toad.client.welcome import ChannelListing, ThreadListing, WelcomeBanner
from toad.client.referenced_core import ReferencedCore
from toad.client.submission import MessageDestination
from toad.client.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.client.subscribers import SidebarSubscriber
from toad.sidebar_changes import SidebarChange
from toad.sidebar_contracts import (
    ChannelGroupRows,
    GroupedSidebar,
    NavigationRefresh,
)
from contextlib import nullcontext
from toad.sidebar_model_view import SidebarStateMachine
from toad.client.tab_identity.kinds import CommsTab
from toad.command_catalog import CommandCatalog
from toad.constants import WELCOME
from toad.core.events import CoordinationObserved, TabHistoryChanged
from toad.message_rows import MarkdownMessageStyle
from toad.launch_binding import NoAgent
from toad.navigation_context import NoNavigationOwner
from toad.client.session_scope import ProjectSessionOrigin
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import PanelSpec
from toad.navigation_context import NavigationContext
from toad.navigation_target import (
    HistoryRouted, KnownThreadTarget, NavigationTarget, channel_target,
)
from toad.history_jump import JumpsHistory, JumpsToLatest
from toad.qt.action_shortcuts import bind_action_shortcuts
from toad.qt.activity import ChannelActivity, PeerActivity
from toad.qt.command_form import WindowCommandOrigin
from toad.qt.composer import ChannelComposer, ComposerHost, MessageComposer
from toad.qt.host import QtCommsHost, ScreenWideWindow
from toad.qt.history import NoTask, QtConversationHistory, QtHistoryWindow, QtMessageFragment, QtWireFragment
from toad.menus import MenuCommand, MenuConversation, message_menu, standard_commands
from toad.client.menu_entry import MenuEntry, strip_menu_markup as _strip_menu_markup_shared
from toad.client.relationship_row_menu import menu_entries_for_row
from toad.qt.menu import QtMenu
from toad.qt.project_panel import QtProjectPanel
from toad.qt.sidebar_panel import QtSidebarPanelFrame
from toad.qt.paste_profile import QtProfilePastePanel
from toad.qt.lines import QtLineRenderer
from toad.qt.goal import QtGoalBar
from toad.qt.placement import SessionArrangementStore, SidebarPane, SidebarToggle, ThreadSettingsPane
from toad.qt.question import QtQuestion
from toad.view_actions import ViewAction
from toad.session_host import SessionEntries, SessionNavigator, WorkspaceViews
from toad.sidebar_layout import SidebarControlsOwner, SidebarLayout
from toad.sidebar_placement import ChannelsSidebarPlacement, SidebarPlacement, ThreadSidebarPlacement
from toad.status_thread import StatusOwner
from toad.target_commands import TargetContext
from toad.terminal_origin import TerminalOrigin
from toad.work_preparation import PreparationRuntime


class ConversationOpen(OperationKind, ExclusiveKind):
    """Opens a tapped row's conversation in its tab; a newer tap supersedes the running one."""


class MessageSend(OperationKind):
    """Sends one message; sends run side by side and are never superseded."""


class CommandRead(OperationKind, ExclusiveKind):
    """Reads the conversation's command catalog for its composer; a newer read supersedes it."""


class MenuActionRun(OperationKind):
    """One application action chosen from the menu."""


def _block_menu_commands(fragment: object) -> Iterator[MenuCommand]:
    """The shared family-derived command list for ``fragment``, plus the bus-specific
    commands `message_menu` adds for a message row. Owner is `toad.menus.standard_commands`;
    both frontends consume it so a new command declared in `src/toad/menus.py` reaches the
    Qt phone without any edit at this site."""
    yield from standard_commands(fragment)
    row = getattr(fragment, "row", None)
    if isinstance(fragment, QtMessageFragment) and row is not None:
        yield from message_menu(row)


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
        most lines. Legacy label-only API kept for bus rows which still use OfferedAction."""
        return ()

    def menu_entries(self, listing: Welcome) -> tuple[MenuEntry, ...]:
        """Rich menu-entry source — the single shape both frontends consume. A row that
        has only label+run `held_actions` is adapted via `MenuEntry.from_offered`; a
        row whose menu items come from a shared helper (e.g. `ConversationRow`
        → `menu_entries_for_row`) returns the helper's output directly."""
        return tuple(MenuEntry.from_offered(action) for action in self.held_actions(listing))


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


class StatusSection(SidebarSection):
    """The one-line status row at the top of the sidebar: a BoundSidebar's observation
    status (`Connecting…`, `Behind`) or a FailedSidebarState's error line. The row is kept
    across sibling-row updates by its fixed key so expansion state and taps survive."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.key = "__status__"


class ConversationRow(SidebarItem):
    """A row that opens its target through the target's own polymorphic `open(context)`.

    `target` is a `NavigationTarget` (not specifically a `HistoryRouted`) because threads
    open via `KnownThreadTarget` → `thread_navigation.open` → `MailboxTab` → agent-bound
    view, while channels open via `channel_target()` → `session_navigation.history` →
    `CommsTab` → wire view. One row class, two destinations; the target picks.
    """

    def __init__(self, target: NavigationTarget) -> None:
        super().__init__()
        self.key = target.name
        self.target = target

    @classmethod
    def channel(cls, name: str, channel, *, badge: str) -> ConversationRow:
        row = cls(channel_target(name))
        row.draw(badge, channel.label(), channel.summary(), channel.tooltip())
        return row

    @classmethod
    def thread(cls, name: str, thread, *, pinned: bool = False,
               pending_detail: str | None = None, badge: str) -> ConversationRow:
        """Thread rows (CLI inbox, mailbox) open as `KnownThreadTarget` so the tap
        routes through `thread_navigation.open` → `MailboxTab` → agent-bound view,
        mirroring Textual's `comms_sidebar.ThreadRow` at `widgets/comms_sidebar.py:242`
        which also carries the incarnation so no round-trip to Core is needed before
        the tab mounts.

        `pinned` and `pending_detail` match the arguments Textual passes at
        `comms_sidebar.py:165` (pinned from `channel.pinned_members`) and
        `comms_sidebar.py:243` (pending_detail from `app.thread_actions.pending`).
        The shared `ThreadRowModel.tooltip(pinned, pending_detail)` owns how both
        flow into the hover text; the label gets a `"* "` prefix when pinned,
        matching `ChannelRowModel.label` which also prefixes its own name."""
        row = cls(KnownThreadTarget(name, thread.incarnation))
        row.draw_thread(thread, pinned=pinned, pending_detail=pending_detail, badge=badge)
        return row

    def draw_thread(self, thread, *, pinned: bool = False,
                    pending_detail: str | None = None, badge: str) -> None:
        """Repaint this row from a `ThreadRowModel`, honoring pin and pending-action.
        Shared with the initial construction path above so every thread-row draw —
        first paint, `sync_members` reconcile, `repaint_members` refresh — goes
        through the same pin/pending-aware assembly. `badge` comes from the caller
        (`app.settings.sidebar.unread_counts.badge(thread.unread)`) so this view
        honors the user's shown-unread-count preference, the same way Textual
        does at `widgets/comms_sidebar.py:244`."""
        label = f"{'* ' if pinned else ''}{thread.label}"
        summary = pending_detail if pending_detail is not None else thread.summary
        self.draw(
            badge, label, summary,
            thread.tooltip(pinned=pinned, pending_detail=pending_detail),
        )

    def activate(self, window: QtToadApp) -> None:
        window.open_row(self)

    def menu_entries(self, listing: Welcome) -> tuple[MenuEntry, ...]:
        """Long-press menu for a conversation row: the shared Open/Copy items the
        Textual sidebar's `widgets/thread_comms.show_row_menu` offers for its
        RelationshipRows, via the single `menu_entries_for_row` helper."""
        host = listing.host
        return menu_entries_for_row(
            target_name=self.target.name,
            copy=host.copy_to_clipboard,
            open_callback=lambda: host.open_row(self),
        )


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
    def keep(self, lines: KeptLines, model: SidebarModel,
             badge_of: Callable[[object], str]) -> None:
        for name in self.listed(model):
            channel = model.channels.rows[name]
            lines.keep(ConversationRow.channel(name, channel, badge=badge_of(channel.unread)))


class QtThreadListing(ThreadListing):
    def keep(self, lines: KeptLines, model: SidebarModel,
             badge_of: Callable[[object], str]) -> None:
        for name in self.listed(model):
            thread = model.threads.rows[name]
            lines.keep(ConversationRow.thread(name, thread, badge=badge_of(thread.unread)))


class WelcomeContent:
    """What the welcome lists above its buses: nothing until the bus answers."""

    def draw(self, top: KeptLines, badge_of: Callable[[object], str]) -> None:
        pass


@dataclass(frozen=True)
class ListedModel(WelcomeContent):
    """The channels and threads the shared welcome lists."""

    model: SidebarModel
    listings: ClassVar[tuple[QtChannelListing | QtThreadListing, ...]] = (QtChannelListing(), QtThreadListing())

    def draw(self, top: KeptLines, badge_of: Callable[[object], str]) -> None:
        """`badge_of` is the caller's resolved `settings.sidebar.unread_counts.badge`
        classmethod; the listing passes each row's `unread` through it so the welcome
        honors the shown-unread-count preference the same way Textual does at
        `widgets/comms_sidebar.py:80`."""
        for listing in self.listings:
            with top.group(OpenSection(listing.TITLE)) as lines:
                listing.keep(lines, self.model, badge_of)


@dataclass(frozen=True)
class ListedFailure(WelcomeContent):
    """The bus could not be read: say why."""

    observed: FailedObservation

    def draw(self, top: KeptLines, badge_of: Callable[[object], str]) -> None:
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
        """``point`` is in the tree's viewport, where QAbstractScrollArea reports it.
        Reads the row's `menu_entries` — the richer single contract every row answers
        (base rows adapt their `held_actions` via `MenuEntry.from_offered`, rich rows
        like `ConversationRow` return the shared `menu_entries_for_row` output
        directly)."""
        rows = self.listing.rows
        item: SidebarItem | None = rows.itemAt(point)
        if item is None:
            return
        entries = item.menu_entries(self.listing)
        if entries:
            self.listing.host.offer_entries(entries)


class QtWelcomeOrigin(ProjectSessionOrigin):
    """Standalone origin for Qt's welcome tab: Qt's `Welcome` widget cannot inherit
    `ProjectSessionOrigin` itself because `SessionOrigin`'s `AbstractHooksMeta` clashes
    with QWidget's shiboken6 metaclass, so the origin is a sibling object the window
    hands to `thread_navigation.open` through `QtWorkspaceViews.origin(WELCOME)`.

    Textual's `WelcomeScreen` (`screens/welcome.py:234`) inherits `ProjectSessionOrigin`
    directly because its widget metaclass does not clash."""

    is_attached: bool = True

    def __init__(self, app: QtToadApp) -> None:
        self.app = app
        self.project_path = app.project_dir

    @property
    def coordination_root(self):
        return self.app.coordination_access.observation.observed().root

    @property
    def thread_identity(self):
        from toad.thread_identity import ThreadIdentity
        observed = self.app.coordination_access.observation.observed()
        return ThreadIdentity(
            observed.user_identity(self.project_path).incarnation,
            str(observed.root),
        )


class QtNewSessionButton(QPushButton):
    """Qt's New Session button on the welcome: fires the shared
    `NewSessionAction` so this frontend starts a session the same way Textual's
    `StartSessionButton` and the welcome's `n` key do. The action owner lives on
    `toad.client.application_actions.NewSessionAction`; the button holds no
    policy of its own."""

    def __init__(self, window: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__("New session", parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setMinimumHeight(40)
        self._host = window
        self.clicked.connect(self._fire)

    def _fire(self) -> None:
        self._host.run_operation(
            MenuActionRun, partial(NewSessionAction().apply, self._host)
        )


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
        self.project = BusLabel(window)
        self.project.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project.setStyleSheet(window.renderer.color_style(MutedRole))
        self.new_session_button = QtNewSessionButton(window, parent=self)
        self.rows = ConversationRows(window)
        self.held_menu = HeldRowMenu(self)
        self.address = BusAddress(window)
        layout = QVBoxLayout(self)
        layout.addSpacing(24)
        layout.addWidget(self.banner)
        layout.addWidget(self.project)
        layout.addSpacing(8)
        layout.addWidget(self.new_session_button)
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
        # `settings.sidebar.unread_counts` is a `ShownUnreadCount` family member whose
        # `.badge(unread)` classmethod honors the user's preference (always show, hide
        # counts, hide badges). The welcome content and bus rows pass each row's
        # `unread` through this so Qt matches Textual's behavior (`widgets/comms_sidebar.py:80`).
        badge_of = self.host.settings.sidebar.unread_counts.badge
        self.content.draw(top, badge_of)
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
        # Alternating row backgrounds come from the shared `generate_tree_widget_style`
        # stylesheet, which already declares `alternate-background-color:
        # {cs.alternate_row_bg}` from the scheme. The sidebar tree enables Qt's
        # alternating flag so that color actually paints — no Qt-local color constant,
        # the scheme stays the single owner. The earlier removal of this flag (to work
        # around a kinetic-scroll flicker) was lifted once PR #1952's shared
        # `respond_to_scroll` throttle landed, which fixed the flicker at its real
        # owner instead of by removing the scheme-driven stripe.
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


class NoopNavigation(NavigationRefresh):
    """Qt does not yet maintain a shared navigation cursor across the sidebar tree."""

    def apply(self) -> None:
        return


class QtChannelGroup(ChannelGroupRows):
    """One channel's section in the Qt sidebar, backed by its persistent `ConversationRow`
    item. Implements the `ChannelGroupRows` contract so `ChangedChannels` and
    `ChangedThreads` dispatch directly through `GroupedSidebar.apply_comms` without a full
    tree rebuild — only the affected header + member thread rows touch Qt.
    """

    def __init__(self, sidebar: Sidebar, name: str, row: ConversationRow) -> None:
        self.sidebar = sidebar
        self.name = name
        self.row = row
        self.channel: ChannelRowModel | None = None
        # Per-member thread rows this group currently shows, by thread key.
        self.member_rows: dict[str, ConversationRow] = {}

    @property
    def member_keys(self):
        model_state = self.sidebar.model_state
        if not model_state.shows_model():
            return ()
        channel_row = model_state.shown.channels.rows.get(self.name)
        return channel_row.members if channel_row is not None else ()

    def present(self, channel: ChannelRowModel) -> frozenset[str]:
        """Repaint the channel header; return members whose pinned state changed so the
        channel-change path can sync them without touching unrelated threads."""
        previous = self.channel
        self.channel = channel
        badge = self.sidebar.window.settings.sidebar.unread_counts.badge(channel.unread)
        self.row.draw(badge, channel.label(), channel.summary(), channel.tooltip())
        if previous is None:
            return frozenset()
        return previous.pinned_members ^ channel.pinned_members

    def sync_members(self, changed: frozenset[str]) -> None:
        """Reconcile this channel's thread rows against the model: add missing, remove
        stale, update rows whose key is in ``changed`` or whose model row moved."""
        model_state = self.sidebar.model_state
        if not model_state.shows_model():
            return
        threads = model_state.shown.threads.rows
        channel_row = model_state.shown.channels.rows.get(self.name)
        if channel_row is None:
            return
        wanted = tuple(channel_row.members)
        wanted_set = frozenset(wanted)
        # Drop member rows the channel no longer lists.
        for name in list(self.member_rows):
            if name not in wanted_set:
                item = self.member_rows.pop(name)
                index = self.row.indexOfChild(item)
                if index >= 0:
                    self.row.takeChild(index)
        # Add/update in the model's order. A row whose name is in ``changed`` repaints;
        # a row at the wrong position moves without a rebuild.
        pending = self.sidebar.window.thread_actions.pending
        badge_of = self.sidebar.window.settings.sidebar.unread_counts.badge
        for index, name in enumerate(wanted):
            thread = threads.get(name)
            if thread is None:
                continue
            pinned = name in channel_row.pinned_members
            pending_detail = pending.get(name)
            existing = self.member_rows.get(name)
            if existing is None:
                item = ConversationRow.thread(name, thread, pinned=pinned,
                                              pending_detail=pending_detail,
                                              badge=badge_of(thread.unread))
                self.row.insertChild(index, item)
                self.member_rows[name] = item
            else:
                if name in changed:
                    existing.draw_thread(thread, pinned=pinned, pending_detail=pending_detail,
                                         badge=badge_of(thread.unread))
                current_index = self.row.indexOfChild(existing)
                if current_index != index:
                    self.row.takeChild(current_index)
                    self.row.insertChild(index, existing)

    def repaint_members(self, names: frozenset[str]) -> None:
        """Repaint any of this group's shown rows whose thread key is in ``names``.
        Membership changes come through ``sync_members`` instead."""
        model_state = self.sidebar.model_state
        if not model_state.shows_model():
            return
        threads = model_state.shown.threads.rows
        channel_row = model_state.shown.channels.rows.get(self.name)
        pinned_members = channel_row.pinned_members if channel_row is not None else frozenset()
        pending = self.sidebar.window.thread_actions.pending
        badge_of = self.sidebar.window.settings.sidebar.unread_counts.badge
        for name in self.member_rows.keys() & names:
            thread = threads.get(name)
            if thread is None:
                continue
            self.member_rows[name].draw_thread(
                thread, pinned=name in pinned_members, pending_detail=pending.get(name),
                badge=badge_of(thread.unread),
            )


class QtSidebarSearch(QWidget):
    """The sidebar's multi-panel shell: stacks the shared `SidebarFilter`'s input
    over a column of `QtSidebarPanelFrame`s, each wrapping one content widget. Today
    the only panel is the conversations tree; follow-up PRs split the project panel
    (and anything else) into siblings keyed by their own `PanelSpec.title`.

    Each panel reads/writes its collapsed state through the shared
    `app.sidebar_state.panels_collapsed` owner so the two frontends agree on which
    panel is open — same key, same writer, identical to Textual's
    `SideBar._compose_shell` which stacks `SidebarSearch` + a viewport of
    `SideBarCollapsible` panels for the same reason.

    The input writes `sidebar.filter.text`; the tree's `_on_filter_changed`
    subscriber re-presents. The name `QtSidebarSearch` stays for now to avoid
    churn in callers; the class is the shell, not just the input."""

    CONVERSATIONS_PANEL = PanelSpec(title="Conversations", flex=True, id="conversations")

    def __init__(self, sidebar: "Sidebar", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.sidebar = sidebar
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setText(sidebar.filter.text)
        self.search_input.textChanged.connect(self._on_text_changed)
        # The tree is one panel in the multi-panel shell. Future listings become
        # siblings (project files, buses, etc.) each with their own `PanelSpec`.
        self.conversations_panel = QtSidebarPanelFrame(
            self.CONVERSATIONS_PANEL, sidebar, sidebar.window.sidebar_state, parent=self,
        )
        self.panels: list[QtSidebarPanelFrame] = [self.conversations_panel]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(4)
        layout.addWidget(self.search_input)
        for panel in self.panels:
            layout.addWidget(panel, 1 if panel.spec.flex else 0)

    def add_panel(self, spec: PanelSpec, body: QWidget) -> QtSidebarPanelFrame:
        """Append a sibling panel to the shell. Follow-up PRs call this to lift the
        project panel (and anything else) out of the conversations tree into its
        own collapsible frame keyed by its own spec."""
        panel = QtSidebarPanelFrame(spec, body, self.sidebar.window.sidebar_state, parent=self)
        self.panels.append(panel)
        layout = self.layout()
        if isinstance(layout, QVBoxLayout):
            layout.addWidget(panel, 1 if spec.flex else 0)
        return panel

    def _on_text_changed(self, value: str) -> None:
        self.sidebar.filter.text = value


class Sidebar(WorkspaceHosted, SidebarStateMachine, ConversationRows):

    @property
    def screen(self) -> WorkspaceFrame:
        return self.window()

    """The bus's channels, each opening to the threads in it, and every thread, from the
    shared sidebar model. State comes from the shared `SidebarStateMachine`: a
    `Detached`/`FailedSidebarState`/`Behind`/`Current` transition drives both the status
    line this sidebar owns and the row redraw. Lines are kept in place across updates, so
    groups stay open or closed and a press stays on its row.

    Structurally satisfies `GroupedSidebar` (declared in `sidebar_contracts`) so
    `ChangedChannels` and `ChangedThreads` dispatch through the shared
    `SidebarChange.apply_comms` path: only the affected channel header + its changed
    member rows touch Qt, instead of a wholesale tree rebuild. (A direct inheritance
    would collide Qt's widget metaclass with `AbstractHooksMeta`; registration isn't
    needed because consumers access the surface structurally, no isinstance checks.)
    """

    navigation: NavigationRefresh = NoopNavigation()
    groups: dict[str, QtChannelGroup]
    open_views: dict[str, str]

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self._status_text: str | None = None
        self.groups = {}
        self.open_views = {}
        # The shared owner of the sidebar's search text and row-match decision. The
        # QLineEdit hosted by `QtSidebarSearch` writes the user's text into this
        # instance; `draw_lines` / `QtChannelListing.keep` / `QtThreadListing.keep`
        # ask the filter's `matches(name)` when deciding whether a row joins the
        # tree. Textual's `SideBar` also owns one (same class, same match rule).
        self.filter: SidebarFilter = SidebarFilter()
        self.filter.subscribe(self._on_filter_changed)

    def _on_filter_changed(self, _value: str) -> None:
        """Re-present the whole tree so rows whose names newly stop (or newly start)
        matching the filter appear / disappear. `present` is already the one wholesale
        redraw, so routing the refresh through it keeps the filter path identical to
        every other model-change path."""
        self.present()

    def accepts_observation(self) -> bool:
        """The sidebar always shows while it exists: the window hides it through
        placement, not through the observation."""
        return True

    def coordination_access(self):
        return self.window.coordination_access

    def show_status(self, text: str) -> None:
        """Record the status; `present` below paints it in one redraw along with rows."""
        self._status_text = text

    def hide_status(self) -> None:
        self._status_text = None

    def present(self, **changes: object) -> None:
        """Run the state transitions, then paint status + rows + welcome. A targeted
        `ChangedChannels` / `ChangedThreads` dispatched into `sync` touches only the
        affected channel header + its member rows; broader state changes fall through
        to the wholesale redraw that rebuilds the whole tree."""
        change = changes.get("change")
        super().present(**changes)
        model = self.model_state.shown if self.model_state.shows_model() else None
        if model is not None and change is not None and change.partial_update:
            # The `sync` dispatch handled the typed partial update. Keep the status row
            # fresh in place without rebuilding the rest of the tree.
            self._refresh_status_only()
        else:
            def draw(top: KeptLines) -> None:
                if self._status_text is not None:
                    top.keep(StatusSection(self._status_text))
                if model is not None:
                    self.draw_lines(model, top)
            self.redraw(draw)
            # A wholesale redraw rebuilt the channel items; rebind the per-channel groups
            # against the new items so the next targeted `sync` operates on live children.
            if model is not None:
                self._rebind_groups_from_tree(model)
            else:
                self.groups = {}
        if model is not None:
            self.window.workspace_sessions.home.present(model)
            self.window.paint_tabs()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Dispatch a typed row change through `GroupedSidebar.apply_comms` so only the
        affected header + member rows touch Qt. Wholesale changes (partial_update=False)
        are left to the caller's follow-up `present()` to rebuild the tree."""
        if not self.model_state.shows_model() or not change.partial_update:
            return
        change.apply_comms(self, self.model_state.shown.channels.rows)

    def model_replaced(self) -> None:
        """Clear rows before the new observation's redraw lands; the next `present` will
        repaint the status and the new model's rows together."""
        self._status_text = None
        self.groups = {}
        self.redraw(lambda top: None)

    def find_open_views(self) -> dict[str, str]:
        """Which channels Qt currently shows an open tab for. The Qt sidebar does not
        yet hoist this out of the tab bar, so the hook returns the stored map (populated
        elsewhere when tab routing lands)."""
        return self.open_views

    def reconcile_members(self):
        """Textual holds a DOM-level sync boundary here; Qt touches items directly."""
        return nullcontext()

    def draw_lines(self, model: SidebarModel, top: KeptLines) -> None:
        threads = model.threads.rows
        matches = self.filter.matches
        pending = self.window.thread_actions.pending
        badge_of = self.window.settings.sidebar.unread_counts.badge
        for name, channel in model.channels.rows.items():
            # A channel stays visible if its name matches OR any of its member thread
            # names do; hiding a channel whose only match is a buried thread would also
            # hide the thread. The group opens whichever path kept it.
            members_shown = [m for m in channel.members if matches(m)]
            if not matches(name) and not members_shown:
                continue
            pinned_members = channel.pinned_members
            with top.group(ConversationRow.channel(name, channel, badge=badge_of(channel.unread))) as group:
                for member in members_shown:
                    thread = threads[member]
                    group.keep(ConversationRow.thread(
                        member, thread,
                        pinned=member in pinned_members,
                        pending_detail=pending.get(member),
                        badge=badge_of(thread.unread),
                    ))
        with top.group(SidebarSection("Threads")) as everyone:
            for name, thread in threads.items():
                if not matches(name):
                    continue
                everyone.keep(ConversationRow.thread(
                    name, thread, pending_detail=pending.get(name),
                    badge=badge_of(thread.unread),
                ))

    def _refresh_status_only(self) -> None:
        """Update just the status row at the top of the tree in place, without touching
        the channel subtrees that a targeted sync just redrew."""
        root = self.invisibleRootItem()
        status_item = None
        for index in range(root.childCount()):
            child = root.child(index)
            if isinstance(child, StatusSection):
                status_item = child
                break
        if self._status_text is None:
            if status_item is not None:
                root.takeChild(root.indexOfChild(status_item))
            return
        target = StatusSection(self._status_text)
        if status_item is None:
            root.insertChild(0, target)
            target.placed()
        else:
            status_item.draw(*target.drawn)

    def _rebind_groups_from_tree(self, model: SidebarModel) -> None:
        """A wholesale redraw rebuilt the tree's top-level items, so the previous
        `QtChannelGroup` instances now point at detached rows. Walk the current tree
        and rebuild the groups map so the next targeted sync hits live children."""
        channel_models = model.channels.rows
        root = self.invisibleRootItem()
        rebuilt: dict[str, QtChannelGroup] = {}
        for index in range(root.childCount()):
            item = root.child(index)
            if not isinstance(item, ConversationRow):
                continue
            name = item.key
            if name not in channel_models:
                continue
            group = QtChannelGroup(self, name, item)
            group.channel = channel_models[name]
            # Index the thread children the wholesale redraw just placed.
            for child_index in range(item.childCount()):
                child = item.child(child_index)
                if isinstance(child, ConversationRow):
                    group.member_rows[child.key] = child
            rebuilt[name] = group
        self.groups = rebuilt

    def bind_failed_observation(self, observed: FailedObservation) -> None:
        super().bind_failed_observation(observed)
        self.window.workspace_sessions.home.present_failed(observed)


class QtSessionEntry(SessionEntries):
    """The Qt window's entry family."""


class QtHistorySessionEntry(QtSessionEntry, HistorySessionEntry, shows=(CommsTab,)):
    """The shared conversation entry, drawn in this window's ConversationView."""

    def __call__(self, sessions: SessionNavigator) -> ConversationView:
        return ConversationView(sessions.app, self)


class BusLabel(ElidedLine):
    """Where the bus this window reads lives, as its connection names it. A Qt client is
    always remote, so its own launch directory (on the phone, /data/data/…/app) says nothing
    about the Core it shows; the connection's location does."""

    def __init__(self, window: QtToadApp) -> None:
        location = window.coordination_access.connection.location
        super().__init__(location)
        self.setToolTip(location)


class ConversationView(JumpsHistory, MenuConversation, Page, StatusOwner, SessionScope, SubmissionView, WireView,
                       HistoryNotifications, ComposerHost, WorkspaceHosted, FlashHost, QWidget,
                       metaclass=PyQtWidgetMeta):

    @property
    def screen(self) -> WorkspaceFrame:
        return self.window()

    """One conversation tab: its history, paged lazily by the pager Textual's channels use
    and drawn as virtual rows, read again whenever Core's stores change; the info row over
    its thread's status; and the composer and activity its kind chooses, sending through
    the shared submissions and running slash commands through the shared catalog as
    Textual's conversation view does. It is a conversation view, so it runs the view
    commands (ComposerHost brings the contract). Also a `MenuConversation`: a long-press
    or right-click on a message row opens the shared block menu through the host's
    `offer` panel, iterating the `MenuCommand` family on the fly."""

    # Default until the live WireSource is wired in __init__: `BusSubmissions.queue_evidence`
    # reads `self.view.queue_source`, so an unset attribute AttributeErrors the first paint.
    # The Textual sibling (CommsChatView, widgets/comms_chat.py) carries the same default.
    queue_source: QueueSource = NoQueueSource()

    def __init__(self, app: QtToadApp, entry: QtHistorySessionEntry) -> None:
        super().__init__()
        self.app, self.entry = app, entry
        self.submissions = BusSubmissions(self)
        self.content_ready = asyncio.Event()
        self.notification_work: asyncio.Task | NoTask = NoTask()
        # This view owns which message categories its transcript shows; the history reads the
        # selection through `selected_categories` and the thread settings pane writes it.
        self.visible_categories = all_categories()
        # The fragment the viewer most recently long-pressed, if any; menu commands read
        # it to know which block they act on.
        self.held_fragment: QtWireFragment | None = None
        label = entry.unobserved_tab().label()
        self.messages = QtHistoryWindow(app.renderer.scheme)
        self.messages.block_menu_requested.connect(self.open_block_menu)
        self.message_history = QtConversationHistory(self.messages, self, app)
        source = app.source()
        # WireSource IS a BusQueueSource (client/history.py:372); storing it on
        # self.queue_source lets BusSubmissions.queue_evidence read pending/queued/held
        # state the same way CommsChatView does (widgets/comms_chat.py:124-129).
        wire = WireSource(
            source.root, self.conversation, source.project, entry.viewer, MarkdownMessageStyle(),
            access=app.coordination_access, core=source.core, fragments=QtWireFragment)
        self.queue_source = wire
        self.message_history.initialize_source(wire)
        self.message_history.observe_source()
        self.label = ElidedLine(label)
        self.status = ElidedLine()
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status.setStyleSheet(app.renderer.color_style(MutedRole))
        self.directory = BusLabel(app)
        self.directory.setStyleSheet(app.renderer.color_style(MutedRole))
        info = QHBoxLayout()
        info.setContentsMargins(6, 0, 6, 0)
        info.addWidget(self.directory, 1)
        info.addWidget(self.label)
        info.addWidget(self.status, 2)
        self.composer = self.conversation.prompt(self)
        self.composer.labelled(label)
        self.activity = tuple(self.conversation.compose_activity(self))
        # The inline consent prompt ("did you mean it?", edit/clear confirmations) — hidden
        # until the conversation asks, mounted below the composer so the picks sit where
        # the next message would be typed, mirroring Textual's Prompt.ask.
        self.question = QtQuestion(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.messages, 1)
        layout.addLayout(info)
        # The peer's or channel's activity sits on the input, as the TUI draws it: what is
        # happening shows where the next message is typed.
        for line in self.activity:
            layout.addWidget(line)
        layout.addWidget(self.composer)
        layout.addWidget(self.question)
        # Every `ViewAction` subclass binds through the shared family loop. A new
        # subclass adds a key automatically — no edit here — and Textual-only siblings
        # whose `apply()` reaches chrome Qt doesn't carry stay silent via the
        # AttributeError guard in `bind_action_shortcuts`. This view implements
        # `JumpsHistory.back_to_bottom_windows`, so `BackToBottomAction.apply(self)`
        # jumps the right window. Other ViewActions (`ShowSidebarAction`, …) will
        # start firing on Qt the day ConversationView carries their contracts.
        self._view_shortcuts = bind_action_shortcuts(self, ViewAction, self)

    @property
    def back_to_bottom_windows(self) -> tuple[JumpsToLatest, ...]:
        """The conversation's one history window, if it has scrolled off the tail.
        Satisfies `JumpsHistory`; `BackToBottomAction.apply(self)` reads this to jump
        the right window back to its latest row."""
        return (self.messages,) if self.messages.can_jump_to_latest else ()

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
        # A command read in flight would hand its catalog to this composer after the tab's
        # widgets are deleted (ComposerEditor, build26). Reads are exclusive across views, so
        # the one running may be another tab's; that composer asks again on its next
        # keystroke while it has no commands (Composer.refresh_offers).
        self.app.cancel_operations(CommandRead)
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

    def compose_peer_activity(self, peer: ThreadIncarnation) -> Iterator[QtGoalBar | PeerActivity]:
        # The peer's goal sits over its activity and the composer, as the TUI's goal bar
        # sits over its prompt.
        yield QtGoalBar(self.app, self.app.renderer, peer)
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
        return await CommandCatalog.read(self.app, (), self.command_target_context(), self.local_commands)

    def update_slash_commands(self) -> None:
        self.app.run_operation(CommandRead, self.read_commands)

    async def read_commands(self) -> None:
        self.composer.set_commands((await self.read_command_catalog()).commands)

    def flash(self, text: str) -> None:
        self.app.status_line.show_status(text, StatusColorRole.INFO)

    def flash_success(self, text: str) -> None:
        self.app.status_line.show_status(text, StatusColorRole.SUCCESS)

    def flash_error(self, text: str) -> None:
        self.app.show_error(text, "Conversation")

    def ask(self, options, title: str = "", get_content=None, callback=None):
        """Show an inline question with these options, mirroring Textual's Conversation.ask.

        A `toad.widgets.question.Ask` is passed to the mounted `QtQuestion`, which pops up
        under the composer with an option button per answer and fires `callback(answer)`
        when the user picks. Returns the Ask for the backend to track."""
        from toad.widgets.question import Ask
        ask = Ask(title, options, get_content, callback)
        self.question.update(ask)
        return ask

    # Sending, through the shared submissions (SubmissionView)

    def submit(self, text: TypedText) -> None:
        self.app.run_operation(MessageSend, partial(self.start_send, text))

    async def start_send(self, text: TypedText) -> None:
        if await CommandCatalog.execute(text.text, self):
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

    def set_category(self, category, on: bool) -> None:
        """Show or hide one message category in this view's transcript, then draw the shown
        rows again. The selection lives here; the pane reads it back on its next present."""
        selected = self.visible_categories
        self.visible_categories = selected | {category} if on else selected - {category}
        self.message_history.apply_filter()
        # The pane reflects the bound view's selection; a present after the change keeps the
        # checks and the transcript showing the same thing.
        self.app.thread_pane.present()

    def record_input(self, text: str) -> None:
        """The Qt composer recalls no earlier input, so there is no history to keep."""

    def run_submission(self, send: Callable[[], Awaitable[None]]) -> None:
        self.app.run_operation(MessageSend, send)

    def submissions_changed(self) -> None:
        self.composer.show_submitting()

    # Block menu — MenuConversation implementation
    #
    # Right-click or long-press on a message row emits `block_menu_requested` from
    # `QtHistoryWindow`, which `open_block_menu` picks up here. The commands are the
    # shared `MenuCommand` family iterated once; the Textual sibling does the same
    # through `widgets/menu.Menu`. Keeping the action list derived means a new menu
    # command declared in `src/toad/menus.py` reaches Qt without any edit here.

    def open_block_menu(self, fragment: QtWireFragment) -> None:
        self.held_fragment = fragment
        entries = tuple(
            MenuEntry(
                label=_strip_menu_markup_shared(command.description),
                run=partial(self._run_block_menu_command, command),
                key_display=", ".join(type(command).default_keys()),
            )
            for command in _block_menu_commands(fragment)
        )
        if entries:
            self.app.offer_entries(entries)

    def _run_block_menu_command(self, command: MenuCommand) -> None:
        result = command.apply(self)
        if asyncio.iscoroutine(result):
            self.app.run_operation(MenuActionRun, lambda: result)

    # The MenuCommand contract (src/toad/menus.py:MenuConversation):

    def accepts_menu_owner(self, owner: QWidget) -> bool:
        return self.held_fragment is not None

    def copy_block_to_clipboard(self) -> None:
        text = self.held_fragment.body_text if self.held_fragment is not None else ""
        if text:
            self.app.copy_to_clipboard(text)
            self.app.show_info("Copied to clipboard", "Block")

    def copy_block_to_prompt(self) -> None:
        text = self.held_fragment.body_text if self.held_fragment is not None else ""
        if text and hasattr(self, "composer") and hasattr(self.composer, "editor"):
            cursor = self.composer.editor.textCursor()
            cursor.insertText(text)
            self.composer.editor.setFocus()
            self.app.show_info("Copied to prompt", "Block")

    def maximize_block(self) -> None:
        """Qt has no maximize mode yet; the command is offered but logs a notice."""
        self.app.show_info("Maximize is Textual-only for now", "Block")

    def export_block_to_svg(self) -> None:
        """Qt has no SVG export yet; the command is offered but logs a notice."""
        self.app.show_info("SVG export is Textual-only for now", "Block")

    async def interrupt_shell(self) -> None:
        """No shell blocks render on Qt yet, so interrupt is a no-op here."""

    def open_line_link(self, link: LineLink) -> None:
        url = getattr(link, "url", None) or getattr(link, "href", None)
        if url:
            self.app.open_url(str(url))


class QtWorkspaceViews(WorkspaceViews):
    """The Qt window's open views, stacked so the selected one shows; the home page stands
    in for a mode with no view here: the welcome page, or a saved tab this app has not
    opened."""

    def __init__(self, app: QtToadApp) -> None:
        self.app = app
        self.home = Welcome(app)
        self._welcome_origin = QtWelcomeOrigin(app)
        self.pages = QStackedWidget(app)
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
        if identity == WELCOME:
            return self._welcome_origin
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
        # Textual's `WorkspaceViews.prepare` sets `view.id = identity` before mount;
        # Qt was missing this, so `view.id` stayed as the opening view's `""` default
        # and `workspace_sessions.views.get(view.id)` resolved to `None`, which made
        # `ThreadOpening.run` short-circuit "view not in workspace" BEFORE calling
        # `prepared.open` / `mount`. That kept the opening placeholder mounted
        # forever (no `prepared.bind` or lifecycle swap ever ran). Assign the mode
        # here so lookups by id round-trip through `.views`.
        view.id = mode
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

    def swap_page(self, old: SessionScope, new: SessionScope) -> None:
        """Replace `old` with `new` in the pages stack and the views dict,
        preserving the mode slot. Called by `QtToadApp.replace_opening_view`
        when the opening placeholder transitions into the real bound view
        (Qt analogue of Textual's MainScreen handling both phases on one
        instance). The caller is responsible for setting `new.id = old.id`
        before this runs."""
        mode = old.mode
        index = self.pages.indexOf(old)
        was_current = self.pages.currentWidget() is old
        if index >= 0:
            self.pages.removeWidget(old)
            self.pages.insertWidget(index, new)
        else:
            self.pages.addWidget(new)
        if mode in self.views:
            self.views[mode] = new
        if was_current:
            self.pages.setCurrentWidget(new)
        old.deleteLater()


class QtToadApp(ClientApplication, CorePrewarm, QtWorkspaceFrame, QtCommsHost, ScreenWideWindow, QWidget, metaclass=PyQtWidgetMeta):
    """The shared client application on Qt, over the Core a UI profile names: the threads,
    and a tab per open conversation; the bar under them is Toad's: the menu button, back
    and forward through the visit history, and the tabs."""

    session_entries = QtSessionEntry

    def __init__(self, connection: RemoteCoreConnection, project: Checkout,
                 preparation: PreparationRuntime, scheme: ColourScheme) -> None:
        super().__init__(project, preparation, scheme)
        # Walk Core's declaration catalog once up front (shared with the Textual app
        # via CorePrewarm): a cold first tab otherwise imports every agent_comms
        # module under the GIL on its first wire revision / action menu.
        self._prewarm_core_modules()
        self.initialize_client(NoAgent(), connection)
        self.setWindowTitle("Toad")
        self.renderer = QtLineRenderer(scheme)
        self.workspace_sessions = QtWorkspaceViews(self)
        # SidebarLayout is the one owner of the move and float policy; the phone hands it a
        # session store, where the Textual workspace hands it the saved settings. Same policy,
        # same placement model, a store each frontend owns.
        self.sidebar_layout = SidebarLayout(SessionArrangementStore(), TerminalOrigin.of())
        # Each sidebar is a toggle bar and the pane it opens. The channels-and-threads list and
        # the open thread's view settings are the two panes' content; the move and float
        # controls live inside the pane, from the shared family. The channels sidebar is always
        # available; the thread's settings only while a tab is open.
        self.sidebar = Sidebar(self)
        # The channel/thread tree is stacked under a QLineEdit search input that writes
        # into the sidebar's shared `SidebarFilter`; the pane takes the wrapper as its
        # content so the input is visible at the top of the pane, mirroring Textual's
        # `SideBar._compose_shell` which also stacks `SidebarSearch` over its panels.
        self.sidebar_search = QtSidebarSearch(self.sidebar, parent=self)
        # Project files live in their own sibling collapsible panel in the shell —
        # one `QtSidebarPanelFrame` per content, keyed to the shared
        # `SidebarState.panels_collapsed` owner, same pattern Textual uses with
        # `SideBarCollapsible` siblings in `SideBar._compose_shell`. Starts
        # collapsed so phones that don't need the project tree aren't crowded.
        self._sidebar_project_panel = QtProjectPanel(self.project_dir.path, parent=self.sidebar_search)
        self.sidebar_search.add_panel(
            PanelSpec(title="Project", flex=True, collapsed=True, id="sidebar-project"),
            self._sidebar_project_panel,
        )
        self.thread_pane = ThreadSettingsPane(parent=self,
                                              project_path=self.project_dir.path)
        self.channels_pane = SidebarPane(self.sidebar_layout, ChannelsSidebarPlacement,
                                         self.sidebar_search, SidebarControlsOwner,
                                         applied=self.rearrange_sidebars,
                                         parent=self)
        self.thread_settings = SidebarPane(self.sidebar_layout, ThreadSidebarPlacement,
                                           self.thread_pane, SidebarControlsOwner,
                                           applied=self.rearrange_sidebars,
                                           parent=self)
        # Paint the panes with the scheme's sidebar tone. Without this, the panes
        # inherit the parent QWidget's default colour (Qt doesn't auto-fill a QWidget's
        # Window role unless asked), so the themed sidebar surface never reaches the
        # bar. The shared style targets `#SidebarPane` set by formbridge's constructor.
        _pane_qss = self.theme.color_scheme.styles.generate_sidebar_pane_style()
        self.channels_pane.setStyleSheet(_pane_qss)
        self.thread_settings.setStyleSheet(_pane_qss)
        self._panes: dict[type[SidebarPlacement], SidebarPane] = {
            ChannelsSidebarPlacement: self.channels_pane,
            ThreadSidebarPlacement: self.thread_settings,
        }
        # Pane open/closed state lives on `self.sidebar_layout` — the single owner both
        # frontends consult via `is_collapsed` / `set_collapsed`. Before this landed, Qt
        # held its own `_pane_open: dict` that drifted from SidebarLayout's view, which
        # produced the "weird square of nothing" and "wrong bar expands vertically" bugs.
        # A pane docks on any edge the family offers, or floats over the conversation. The
        # float layer is a child of the centre, raised over the pages when a pane floats.
        # Each dock owns the toggle bar and the pane for its edge: a single stack of toggle
        # then pane (leading edges) or pane then toggle (trailing edges), so the bar ends up
        # on the wall wherever the user moves the sidebar.
        self.top_dock, self.bottom_dock = self._dock(), self._dock()
        self.left_dock, self.right_dock = self._dock(), self._dock()
        self._docks = {"top": self.top_dock, "bottom": self.bottom_dock,
                       "left": self.left_dock, "right": self.right_dock}
        # Parent arg is load-bearing on Qt-for-Android: a parentless QWidget created during
        # QtToadApp.__init__ becomes its own top-level window with its own EGL surface, and
        # the pending surface acquisition recurses into the deadlock protector during the
        # first-paint flush (SIGABRT, matching PR #1885's root cause). Every QWidget created
        # here is a child of self; naming self as parent keeps them off the top-level list.
        self.center = QWidget(self)
        grid = QGridLayout(self.center)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.top_dock, 0, 1)
        grid.addWidget(self.left_dock, 1, 0)
        grid.addWidget(self.workspace_sessions.pages, 1, 1)
        grid.addWidget(self.right_dock, 1, 2)
        grid.addWidget(self.bottom_dock, 2, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        # The float layer sits over the pages. Without an opaque background it leaks the
        # conversation's pixels through gaps between the pane's own widgets, which is what
        # made the history look garbled when a sidebar was lifted off a dock onto the float.
        # The stylesheet below paints an opaque plate over the pane's own widgets. We can't
        # use setAutoFillBackground(True) here: Qt-for-Android forces a separate backing
        # store for an autofilled widget, and flushing it during the center's repaint
        # recurses into QAndroidPlatformOpenGLWindow::eglSurface() and trips the deadlock
        # protector (SIGABRT, 2026-11-17 Pixel 8a tombstone). Stylesheet styling paints
        # through the parent's backing store instead, which is what Android needs.
        self.float_layer = QWidget(self.center)
        self.float_layer.setStyleSheet(self.theme.color_scheme.styles.generate_frame_style())
        self._float_layout = QVBoxLayout(self.float_layer)
        self._float_layout.setContentsMargins(0, 0, 0, 0)
        self.float_layer.hide()
        # Two toggle bars side by side above the tabs: an arrow and the heading, as Toad draws
        # them. The move arrows and Float live in the panes, not on these bars.
        self.channels_bar = SidebarToggle(
            self.sidebar_layout, ChannelsSidebarPlacement,
            heading=partial(self._pane_heading, ChannelsSidebarPlacement),
            shown=partial(self.pane_open, ChannelsSidebarPlacement),
            toggled=partial(self.toggle_pane, ChannelsSidebarPlacement),
            parent=self)
        self.thread_bar = SidebarToggle(
            self.sidebar_layout, ThreadSidebarPlacement,
            heading=partial(self._pane_heading, ThreadSidebarPlacement),
            shown=partial(self.pane_open, ThreadSidebarPlacement),
            toggled=partial(self.toggle_pane, ThreadSidebarPlacement),
            parent=self)
        # The toggle bars live wherever their sidebar is placed, not in the bottom chrome:
        # _layout_panes re-parents each bar into its pane's dock, before or after the pane
        # depending on whether the edge is leading (left, top) or trailing (right, bottom).
        self._bars: dict[type[SidebarPlacement], SidebarToggle] = {
            ChannelsSidebarPlacement: self.channels_bar,
            ThreadSidebarPlacement: self.thread_bar,
        }
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
        chrome = QFrame(self)
        chrome.setStyleSheet(self.theme.color_scheme.styles.generate_frame_style())
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        chrome_layout.addWidget(self.status_line)
        # QtMenu is the shared rendering for both the hamburger (application) menu and
        # the row-context (message) menu. Its rows render MenuEntry data (bold key
        # shortcut + label), matching Textual's MenuKey/MenuDescription widgets. Parent
        # is QtToadApp so the menu is a child QWidget, not a top-level QWindow — the
        # EGL-deadlock hazard that killed off QMessageBox applies to any popup window.
        self.menu_panel = QtMenu(self)
        chrome_layout.addWidget(self.menu_panel)
        # Paste surface for the bus-connect remediation ("Paste a profile" option on the
        # BusConnectDecision menu). Inline QFrame child of the window, not a QDialog —
        # same EGL rationale as QtMenu: a top-level popup needs its own surface and
        # deadlocks the compositor on Pixel 8a.
        self.profile_paste_panel = QtProfilePastePanel(self)
        chrome_layout.addWidget(self.profile_paste_panel)
        chrome_layout.addLayout(bar)
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.addWidget(self.center, 1)
        layout.addWidget(chrome)
        self.fit_screen()
        # The welcome lists the channels and threads, so both panes start down.
        self.rearrange_sidebars()
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
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setMinimumSize(48, 44)
        font = button.font()
        font.setPointSizeF(font.pointSizeF() * 1.5)
        button.setFont(font)
        button.clicked.connect(action)
        return button

    def capture_command_origin(self) -> WindowCommandOrigin:
        return WindowCommandOrigin(self)

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
        self.present_panes()

    # The two panes sit behind their bars above the tabs, as on Toad's phone layout: a bar
    # shows or hides its pane and moves or floats it, over the shared SidebarLayout.

    def _dock(self) -> QWidget:
        # Parent self so the dock is a child of QtToadApp from creation, not a top-level
        # QWindow on Android — see the EGL deadlock note on `self.center` above.
        #
        # Every dock uses QHBoxLayout: sidebars sharing one edge sit next to each other
        # along a horizontal line rather than stacking. The edge's own `pane_bar_axis`
        # decides whether each sidebar is flattened into that line (width edges — pane
        # and bar are both columns) or wrapped in a QVBoxLayout group first (height
        # edges — pane and bar stack vertically within the group).
        dock = QWidget(self)
        inner = QHBoxLayout(dock)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        dock.hide()
        return dock

    def pane_open(self, identity: type[SidebarPlacement]) -> bool:
        """Read through SidebarLayout — the single collapsed-state owner. A collapsed
        bar means the pane is NOT open, so pane_open is `not is_collapsed`."""
        return not self.sidebar_layout.is_collapsed(identity)

    def toggle_pane(self, identity: type[SidebarPlacement]) -> None:
        self.sidebar_layout.toggle_collapsed(identity)
        self.rearrange_sidebars()

    def _conversation_open(self) -> bool:
        return self.workspace_sessions.selected is not self.workspace_sessions.home

    def _pane_available(self, identity: type[SidebarPlacement]) -> bool:
        """The thread's settings follow an open conversation; the sidebar is always there."""
        return self._conversation_open() if identity is ThreadSidebarPlacement else True

    def _pane_heading(self, identity: type[SidebarPlacement]) -> str:
        return identity.heading(self._viewed_titles())

    def _viewed_titles(self) -> Iterator[str]:
        if self._conversation_open():
            index = self.tabs.currentIndex()
            if index >= 0:
                yield self.tabs.tabText(index)

    def _bind_thread_pane(self) -> None:
        """The thread's settings follow the open conversation; the welcome is the only other
        page, and it owns none."""
        selected = self.workspace_sessions.selected
        self.thread_pane.bind(selected if self._conversation_open() else None)

    def _target_layout(self, placement: SidebarPlacement):
        """Where a pane goes for its placement: the arrangement names its dock by key, or
        None for a floating pane that joins the float layer. No branch on `floating` /
        `side.dock` here — the PlacementArrangement family answers directly."""
        key = placement.arrangement.dock_key(placement.side)
        return self._float_layout if key is None else self._docks[key].layout()

    def _empty(self, layout) -> None:
        # Park widgets on self (QtToadApp) rather than orphaning them. Qt-for-Android gives
        # any parent-less QWidget its own top-level QWindow + EGL surface, and the second
        # EGL allocation races QtAndroidAccessibility::runInObjectContext() for the
        # eglSurface() mutex and trips the deadlock protector (SIGABRT a second after
        # ApplicationActive). Parenting them to self keeps them as child widgets.
        #
        # Nested layouts (the QVBoxLayout groups `_arrange_sidebar` builds for top/bottom
        # edges) need recursive draining: `takeAt(0).widget()` returns None for a layout
        # item, so without this recursion the widgets inside those groups are left
        # managed by the stale group until the next `addWidget` reparents them — which
        # leaked the group's cached sizeHint into the dock across tab switches.
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
                continue
            sub = item.layout()
            if sub is not None:
                self._empty(sub)

    def _layout_panes(self) -> None:
        for dock in self._docks.values():
            self._empty(dock.layout())
        self._empty(self._float_layout)
        # Reparent bars to self before the next pass rehomes them atomically — keeps them
        # children of QtToadApp throughout, never top-level QWindows.
        for identity, bar in self._bars.items():
            bar.setParent(self)
        for identity, pane in self._panes.items():
            bar = self._bars[identity]
            if not self._pane_available(identity):
                pane.setParent(self)
                pane.hide()
                bar.hide()
                continue
            placement = self.sidebar_layout.get(identity)
            # The PlacementArrangement family (DockedPlacementArrangement for docked,
            # FloatingPlacementArrangement for floating) answers bar-first and axis
            # polymorphically — no `placement.floating or placement.side.sign == 1`
            # branch in window code.
            arrangement = placement.arrangement
            bar_first = arrangement.bar_first(placement.side)
            target = self._target_layout(placement)
            bar.show()
            if self.pane_open(identity):
                pane.show()
                self._arrange_sidebar(target, placement, bar, pane, bar_first=bar_first)
            else:
                pane.setParent(self)
                pane.hide()
                self._arrange_sidebar(target, placement, bar, pane=None, bar_first=bar_first)
        for dock in self._docks.values():
            dock.setVisible(dock.layout().count() > 0)
        # QGridLayout on `self.center` caches column/row sizeHints, and a dock's own
        # resize (when its own layout shrinks after a pane became unavailable, or grew
        # when it became available again) does not always propagate up to the grid's
        # cached cell sizes in Qt-for-Android. Without this invalidate, closing a
        # conversation tab leaves the center column still sized for the old dock extents,
        # so the inter-widget spacing between center and docks goes stale until the next
        # resize event. Textual does not share this quirk — it uses TCSS, not a Qt grid.
        self.center.layout().invalidate()

    def _arrange_sidebar(self, target, placement, bar, pane, *, bar_first: bool) -> None:
        """Add this sidebar's (bar, pane) pair to its target container. The arrangement
        answers the pane/bar axis polymorphically — 'row' means the pair joins the line
        directly (adjacent columns within the dock), 'column' means wrap in a QVBoxLayout
        first (pair stacks vertically inside a cell). A FloatingPlacementArrangement
        answers 'column' regardless of the side it normally occupies.

        The pane gets stretch=1 so it absorbs growth when its sidebar group shares the
        dock with a collapsed sibling; the bar gets stretch=0 so a bar-only group does
        not vertically expand to match the sibling's open pane (the bug Tristan reported
        as "the other bar vertically expands rather than the pane growing above it").
        A bar-only group pads itself with a stretch on the wall-facing end so the bar
        stays pinned to the wall and the group's excess space is empty, not bar."""
        widgets = (bar,) if pane is None else ((bar, pane) if bar_first else (pane, bar))
        axis = placement.arrangement.pane_bar_axis(placement.side)
        if axis == "row":
            for widget in widgets:
                target.addWidget(widget, 1 if widget is pane else 0)
            return
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(0)
        if pane is None:
            # Bar-only group: add a stretch on the wall-facing end so the bar stays pinned
            # to its wall and the excess space is empty, not bar. `bar_first=True` means
            # the bar's wall is the LEADING end (top for TopSidebarEdge), so the empty
            # space goes AFTER the bar; otherwise the bar's wall is the TRAILING end
            # (bottom for BottomSidebarEdge) and the empty space goes BEFORE it.
            if bar_first:
                group.addWidget(bar, 0)
                group.addStretch(1)
            else:
                group.addStretch(1)
                group.addWidget(bar, 0)
        else:
            for widget in widgets:
                group.addWidget(widget, 1 if widget is pane else 0)
        target.addLayout(group, 1 if pane is not None else 0)
        self.reposition_float()

    def reposition_float(self) -> None:
        """The float layer holds whatever pane floats, raised over the lower part of the
        conversation. An empty layer stays hidden. Either way, the workspace repaints so a
        reflow does not leave stale pixels from the layer's previous rectangle on the
        conversation under it."""
        empty = self._float_layout.count() == 0
        if empty:
            self.float_layer.hide()
        else:
            rect = self.center.rect()
            height = max(1, int(rect.height() * 0.45))
            self.float_layer.setGeometry(0, rect.height() - height, rect.width(), height)
            self.float_layer.raise_()
            self.float_layer.show()
        self.workspace_sessions.pages.update()
        self.center.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.reposition_float()

    def present_panes(self) -> None:
        """Lay the panes out for their placements and draw both bars and their controls; the
        thread's bar shows only while a conversation is open."""
        self._layout_panes()
        self._bind_thread_pane()
        self.thread_bar.setVisible(self._conversation_open())
        self.channels_bar.present()
        self.thread_bar.present()
        for pane in self._panes.values():
            pane.present()

    def rearrange_sidebars(self) -> None:
        """A move, float or toggle: lay the panes out again. SidebarLayout has already written
        the arrangement to this session's store."""
        self.present_panes()

    def show_sidebar(self) -> None:
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, False)
        self.present_panes()

    def hide_sidebar(self) -> None:
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, True)
        self.present_panes()

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
        if self.pane_open(ChannelsSidebarPlacement):
            self.hide_sidebar()
        else:
            self.show_sidebar()

    def show_menu(self) -> None:
        """Toad's application actions under their labels and default keybindings, in the
        shared `QtMenu` panel over the bar; a choice runs as its own operation and closes
        the panel. The panel is part of this window: a QMenu or any other top-level
        window needs its own EGL surface and deadlocks the compositor on Android (same
        hazard as the deleted top-level QMessageBox calls)."""
        if self.menu_panel.isVisible():
            self.menu_panel.hide()
            return
        self.menu_panel.show_entries(self._application_menu_entries())

    def _application_menu_entries(self) -> tuple[MenuEntry, ...]:
        """Project ApplicationAction.menu(self) into MenuEntry rows. The key_display
        comes from the action's default InputMode binding; the description is the
        action's own docstring summary, and the run schedules MenuActionRun as before."""
        from formbridge.key_declarations import InputMode  # local: keeps the import graph light
        entries: list[MenuEntry] = []
        for command, label in ApplicationAction.menu(self):
            declaration = type(command)
            keys = declaration.keys.get(InputMode, ())
            entries.append(MenuEntry(
                label=_strip_menu_markup_shared(label),
                run=partial(self.run_operation, MenuActionRun,
                            partial(command.apply, self)),
                key_display=", ".join(keys),
                description=declaration.summary(),
            ))
        return tuple(entries)

    def offer(self, actions: tuple[OfferedAction, ...]) -> None:
        """Legacy label-only API: bus listings' held-finger menu builds `OfferedAction`
        tuples and calls here. Each OfferedAction becomes a MenuEntry with no keyboard
        shortcut and no description, so the shared `QtMenu` renders a plain label column
        — the same widget the hamburger and the message-row menus use."""
        self.offer_entries(tuple(MenuEntry.from_offered(action) for action in actions))

    def offer_entries(self, entries: tuple[MenuEntry, ...]) -> None:
        """Rich-row API: callers that have `MenuEntry` with keybindings and descriptions
        (the hamburger menu, the row-context menu) populate the shared QtMenu directly."""
        self.menu_panel.show_entries(entries)

    def offer_bus_connect(self, decision: BusConnectDecision) -> None:
        """Render the shared bus-connect decision through the same menu panel the hamburger
        and row-context menus use: the summary goes to the status line so the reader sees
        what happened, and each `RemediationOption` becomes a `MenuEntry` the panel draws.
        Qt owns only the paint; the decision's options own the actions."""
        self.show_warning(decision.summary, "Bus")
        if not decision.options:
            return
        entries = tuple(
            MenuEntry(label=option.label, run=option.invoke, description=option.description)
            for option in decision.options
        )
        self.offer_entries(entries)

    def paste_profile(self, submit: Callable[[str], object]) -> None:
        """Open the inline paste panel for a bus-connect profile. Bound to the
        `BusConnectDecision` "Paste a profile" option; a submit holds the pasted JSON
        through `agent_comms-connector hold-ui` and opens its bus."""
        self.profile_paste_panel.open_for(submit)

    def open_row(self, row: ConversationRow) -> None:
        """Open the row's target through the target's own `open(context)` — polymorphic
        so a `KnownThreadTarget` (thread row) routes through `thread_navigation.open`
        → `MailboxTab` → agent-bound view, while a `HistoryRouted` channel row routes
        through `session_navigation.history` → `CommsTab` → wire view. Previously
        this hardcoded `session_navigation.history`, which forced EVERY row (including
        CLI-inbox threads) into the wire view and made them appear bus-only."""
        context = NavigationContext(
            app=self,
            owner_mode=WELCOME,
            project_path=self.project_dir,
            actor="",
        )
        self.run_operation(ConversationOpen, partial(self._open_target, row.target, context))

    async def _open_target(self, target: NavigationTarget, context: NavigationContext) -> None:
        """Route through home: mirrors Textual's `screens/comms.py:254` which also passes
        `WELCOME` as the owner_mode regardless of which tab the row is tapped from.
        `QtWorkspaceViews.origin(WELCOME)` hands `thread_navigation.open` a
        `QtWelcomeOrigin` whose `thread_identity` is observed off the thread so the
        navigator's `origin.current` check can match it."""
        await target.open(context)
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

    def make_opening_view(self, request, origin, identity):
        """Qt's thread-navigation opening placeholder: a `QtOpeningSessionView` (not
        Textual's `MainScreen.opening(...)`). Lazy-import `QtOpeningSessionView` to
        keep `toad.qt.window` import-light at module load. Textual's override lives at
        `src/toad/app.ToadApp.make_opening_view`."""
        from toad.qt.opening_view import QtOpeningSessionView
        return QtOpeningSessionView(request.target)

    def replace_opening_view(self, opening_view, prepared, identity):
        """Qt's opening→bound lifecycle swap. Constructs a `QtMailboxView` from
        `prepared` (thread incarnation + root + project), swaps it into
        `QtWorkspaceViews.pages` + `.views` at the opening view's mode slot, and
        returns the new instance so `ThreadOpening.mount` runs `prepared.bind`,
        `bind_opened`, `_prepare_content` and `wait_content_ready` against the
        bound-state view — the Qt analogue of Textual's MainScreen handling both
        phases on one widget.

        Lazy-imports `QtMailboxView` to keep `toad.qt.window` import-light at
        module load, same pattern as `make_opening_view` above."""
        from toad.qt.mailbox_view import QtMailboxView
        bound = QtMailboxView(self, prepared.project, prepared.thread.incarnation, prepared.root)
        bound.id = opening_view.id
        self.workspace_sessions.swap_page(opening_view, bound)
        return bound

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
        elif self.pane_open(ChannelsSidebarPlacement) and self.workspace_sessions.views:
            self.hide_sidebar()
        elif self.tab_order.history_target(-1) is not None:
            self.tab_order.navigate(-1)
        elif not self.pane_open(ChannelsSidebarPlacement):
            self.show_sidebar()
        else:
            self.close()


# Register Qt's ACP/Mailbox session tab as a sibling entry. Loaded at module tail so
# `toad.qt.acp_tab` can read `Page` and `QtSessionEntry` from here; module-level import
# (rather than `from … import …`) so a partially initialised acp_tab in the same thread
# of entry still resolves on the second half of its own file after window.py returns.
import toad.qt.acp_tab  # noqa: E402, F401
