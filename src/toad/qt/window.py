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
from dataclasses import dataclass, field
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
from toad.qt.submission_view import QtSubmissionView
from PySide6.QtCore import QEvent, QMargins, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from toad.client.category_selection import CategorySelection
from toad.client.view_settings import ConversationSettingsOwner
from toad.client.session_scope import NoConversationView
from toad.client.application_actions import ApplicationAction, NewSessionAction, NewSessionControl
from toad.client.bus_connect import BusConnectDecision
from toad.client.bus_selection import (
    BusChoice,
    BusListing,
    BusPickerHost,
    PickerRow,
    TailnetAnswer,
)
from toad.client.offered_action import OfferedAction
from toad.client.bus_submission import BusSubmissions, ConversationSubmission, SubmissionView, TypedText
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
from toad.application_lifetime import ApplicationStart
from toad.client.platform import host
from toad.client.line_blocks import LineLink, MutedRole
from toad.client.welcome import ChannelListing, ThreadListing, WelcomeBanner
from toad.keyed_rows import KeyedRows
from toad.setting_choices import UnreadCount
from toad.sidebar_rows import ChannelLineText, ChannelRowFace, ThreadLineText, ThreadRowFace
from toad.client.referenced_core import ReferencedCore
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
from toad.core import session_requests
from toad.core.events import CoordinationObserved, TabHistoryChanged
from toad.launch_binding import NoAgent
from toad.navigation_context import NoNavigationOwner
from toad.client.session_scope import ProjectSessionOrigin
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import PanelSpec
from toad.navigation_context import ConversationViewNavigation
from toad.navigation_target import (
    HistoryRouted, KnownThreadTarget, NavigationTarget, channel_target,
)
from toad.history_jump import JumpsHistory, JumpsToLatest
from toad.qt.action_shortcuts import bind_action_shortcuts
from toad.qt.activity import ChannelActivity, PeerActivity, QtObservedSweep
from toad.qt.command_form import WindowCommandOrigin
from toad.qt.composer import ChannelComposer, ComposerHost, MessageComposer
from toad.qt.host import QtCommsHost, ScreenWideWindow
from toad.client.transcript_fragments import TranscriptFragment
from toad.qt.history import QtConversationHistory, QtHistoryNotifications, QtHistoryWindow, QtWireFragment
from toad.menus import MenuCommand, MenuConversation, standard_commands
from toad.client.menu_entry import MenuEntry, strip_menu_markup as _strip_menu_markup_shared
from toad.client.relationship_row_menu import menu_entries_for_row
from toad.qt.menu import QtMenu
from toad.qt.channel_sort import QtChannelListSort, QtChannelSortControl
from toad.qt.thinking_animator import QtThinkingAnimator
from toad.qt.sidebar_panel import QtPanelEntry, QtSidebarPanels, QtSidebarShell
from toad.qt.view_settings import QtViewSettings, capability_widgets
from toad.qt.paste_profile import QtProfilePastePanel
from agent_comms.messaging.display_references import ProjectReferences
from toad.markdown_links import LinkContext
from toad.qt.lines import QtLineRenderer
from toad.client.prompt_composer import ComposerStatus
from toad.prompt_actions import SubmitInputAction
from toad.client.prompt_stack import SuccessTone
from toad.qt.prompt_stack import QtFlash
from toad.qt.goal import QtGoalBar
from toad.qt.placement import SessionArrangementStore, ThreadSettingsPane
from toad.qt.side_bar import QtSideBar, QtWorkspaceChrome
from toad.qt.question import QtQuestion
from toad.view_actions import ViewAction
from toad.session_host import SessionEntries, SessionNavigator, WorkspaceViews
from toad.sidebar_layout import CHANNELS_PANEL, SidebarLayout
from toad.sidebar_placement import (
    ChannelsSidebarPlacement,
    SidebarPlacement,
    ThreadSidebarPlacement,
)
from toad.status_thread import StatusThread, WorkingStatusOwner
from toad.conversation_turn import ConversationTurn
from toad.agent_binding import NoAgentConnection
from toad.target_commands import TargetContext
from toad.terminal_origin import TerminalOrigin
from toad.work_preparation import PreparationRuntime


class CommandRead(OperationKind, ExclusiveKind):
    """Reads the conversation's command catalog for its composer; a newer read supersedes it."""


class MenuActionRun(OperationKind):
    """One application action chosen from the menu."""


def _block_menu_commands(fragment: TranscriptFragment) -> Iterator[MenuCommand]:
    """The shared family-derived command list for ``fragment``, plus the per-fragment
    menu entries each fragment answers via `block_menu`. Owner is
    `toad.menus.standard_commands` for the family-wide list; `TranscriptFragment.block_menu`
    (default `()`) and `BusMessageFragment.block_menu → message_menu(self.row)` decide
    the per-fragment addition without the consumer having to ask what subclass it has."""
    yield from standard_commands(fragment)
    yield from fragment.block_menu


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
        self.setToolTip(0, tooltip)
        self.fit()

    def first_line(self) -> tuple[str, str]:
        """The status prefix and the name the line's first row draws."""
        badge, label, _, _ = self.drawn
        return (f"{badge} " if badge else ""), label

    def fit(self) -> None:
        """Lay the text out for the width the tree gives this line: the name and the summary
        each end in an ellipsis where they would overflow, as Textual's rows elide, rather than
        being cut at the edge. The prefix (status, unread) always shows. Elision is the font's
        own ElideRight, the rule `ElidedLine` draws with."""
        prefix, name = self.first_line()
        summary = self.drawn[2]
        tree = self.treeWidget()
        if tree is not None:
            width = tree.line_width(self)
            metrics = tree.fontMetrics()
            right = Qt.TextElideMode.ElideRight
            name = metrics.elidedText(name, right, max(1, width - metrics.horizontalAdvance(prefix)))
            summary = metrics.elidedText(summary, right, max(1, width - metrics.horizontalAdvance("  ")))
        self.setData(0, LAYOUT_ROLE, StyledTextLayout(
            name=Segment(name), status_prefix=prefix, detail_line=summary, multiline=True))

    def placed(self) -> None:
        """A new line fits its text to the tree it just joined."""
        self.fit()

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
        super().__init__()
        self.key = title
        self.draw("", title, "", "")


class OpenSection(SidebarSection):
    """A welcome section: open as the shared sidebar state says (`welcome_section_open`), so
    it stays as the reader left it however often the listing is drawn again."""

    def placed(self) -> None:
        self.setExpanded(self.treeWidget().window.sidebar_state.welcome_section_open(self.key))

    def activate(self, window: QtToadApp) -> None:
        super().activate(window)
        window.sidebar_state.set_welcome_section_open(self.key, self.isExpanded())


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

    def placed(self) -> None:
        """A new channel line opens as its target opens by default (the feed does), as the
        Textual sidebar's ChannelGroup does."""
        super().placed()
        self.setExpanded(self.target.expanded_by_default)

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


class ThreadLine(ThreadRowFace, ConversationRow):
    """A thread's line: the shared thread line text (`ThreadRowFace`) in the tree's two
    rows. It opens as a `KnownThreadTarget`, carrying the birth, as Textual's ThreadRow does."""

    @classmethod
    def of(cls, name: str, thread, *, pinned: bool, action_status: str | None,
           counts: type[UnreadCount]) -> ThreadLine:
        line = cls(KnownThreadTarget(name, thread.incarnation))
        line.present_thread(thread, pinned=pinned, action_status=action_status, counts=counts)
        return line

    def show_thread_text(self, text: ThreadLineText) -> None:
        self.draw(text.badge, text.pin + text.name, text.detail, text.tooltip)


class ChannelEntry(ChannelRowFace, ConversationRow):
    """A channel's line: the shared channel line text (`ChannelRowFace`)."""

    @classmethod
    def of(cls, name: str, channel, *, counts: type[UnreadCount]) -> ChannelEntry:
        line = cls(channel_target(name))
        line.present_channel(channel, counts=counts)
        return line

    def show_channel_text(self, text: ChannelLineText) -> None:
        self.draw(text.badge, text.label, text.summary, text.tooltip)


class ChannelLine(ChannelEntry):
    """A channel line in the Channels sidebar: its first row is a `HeaderLineControl` (the
    name elided before the channel's order), so the tree's own text draws only the summary
    beneath it."""

    header: HeaderLineControl | None = None

    def first_line(self) -> tuple[str, str]:
        """The header draws the first row; the tree's text is the summary alone."""
        return "", ""

    def draw(self, badge: str, label: str, summary: str, tooltip: str) -> None:
        super().draw(badge, label, summary, tooltip)
        if self.header is not None:
            self.header.show_title(label, badge)


class NewSessionRow(NewSessionControl, SidebarItem):
    """The Channels sidebar's first line, as Textual's `NewSessionButton`: a tap starts a
    thread in the selected project through the shared `NewSessionControl`."""

    key = NewSessionControl.label

    def __init__(self) -> None:
        super().__init__()
        self.draw("", self.label, "", "Start a thread in the selected project")

    def activate(self, window: QtToadApp) -> None:
        window.run_operation(MenuActionRun, partial(self.start_session, window))


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


from toad.qt.page import Page  # re-export: callers already import Page from here
from toad.qt.metrics import UiGap


class QtChannelListing(ChannelListing):
    def keep(self, lines: KeptLines, model: SidebarModel, app: QtToadApp) -> None:
        for name in self.listed(model):
            line = ChannelEntry(channel_target(name))
            line.show_channel_text(self.line_text(model.channels.rows[name], app.settings.sidebar.unread_counts))
            lines.keep(line)


class QtThreadListing(ThreadListing):
    def keep(self, lines: KeptLines, model: SidebarModel, app: QtToadApp) -> None:
        for name in self.listed(model):
            lines.keep(ThreadLine.of(name, model.threads.rows[name], pinned=False,
                                     action_status=app.thread_actions.pending.get(name),
                                     counts=app.settings.sidebar.unread_counts))


class WelcomeContent:
    """What the welcome lists above its buses: nothing until the bus answers."""

    def draw(self, top: KeptLines) -> None:
        pass


@dataclass(frozen=True)
class ListedModel(WelcomeContent):
    """The channels and threads the shared welcome lists.

    `app` and `listings` are instance-owned so each welcome's listings can carry
    app-specific references — previously a `ClassVar` tuple shared across every
    `ListedModel`, which blocked passing `app.thread_actions.pending` (or any other
    app ref) into row construction. The holder is instance-owned now; the listing
    classes themselves (`QtChannelListing`, `QtThreadListing`) stay unchanged, so
    downstream work (reading app.thread_actions.pending for pending_detail, etc.)
    now has a seat at the table via `self.app`."""

    model: SidebarModel
    app: "QtToadApp"
    listings: tuple[QtChannelListing | QtThreadListing, ...] = field(
        default_factory=lambda: (QtChannelListing(), QtThreadListing())
    )

    def draw(self, top: KeptLines) -> None:
        for listing in self.listings:
            with top.group(OpenSection(listing.TITLE)) as lines:
                listing.keep(lines, self.model, self.app)


@dataclass(frozen=True)
class ListedFailure(WelcomeContent):
    """The bus could not be read: say why."""

    observed: FailedObservation

    def draw(self, top: KeptLines) -> None:
        top.keep(UnavailableSection(self.observed))


class Banner(WelcomeBanner, QWidget):
    """Toad's banner, filling the width it is given in whole characters, as the terminal
    draws it: each character in its own cell of the grid. Android's monospace font has no
    box-drawing glyphs, and the fallback's glyphs are wider, so text drawn as a run slid
    every row off the blocks above it. It takes the width and never asks for one."""

    LINES = WelcomeBanner.TEXT.splitlines()  # the shared banner, as Textual's WelcomeTitle draws it
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


class QtStartSessionButton(NewSessionControl, QPushButton):
    """The welcome's New Session, as Textual's `StartSessionButton`: this launch's session
    (`NewSessionAction`), labelled and started through the shared `NewSessionControl`."""

    action = NewSessionAction

    def __init__(self, window: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(self.label, parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setMinimumHeight(40)
        self._host = window
        self.clicked.connect(self._fire)

    def _fire(self) -> None:
        self._host.run_operation(MenuActionRun, partial(self.start_session, self._host))


class Welcome(Page, BusListing, NoConversationView, QWidget):
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
        self.new_session_button = QtStartSessionButton(window, parent=self)
        self.rows = ConversationRows(window)
        self.held_menu = HeldRowMenu(self)
        self.address = BusAddress(window)
        # Gesture hint line below the rows, mirroring Textual's WelcomeNote(HINTS)
        # at the tail of `WelcomeScreen.compose`. The content is owned per-frontend
        # via `self.app.welcome_hints` — Textual carries keyboard shortcuts, Qt
        # carries touch gestures. Strip Textual's `[b]...[/b]` markup for Qt since
        # QLabel doesn't render it natively; the gestures text is plain already.
        self.hints = QLabel(_strip_menu_markup_shared(window.welcome_hints), self)
        self.hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hints.setWordWrap(True)
        self.hints.setStyleSheet(window.renderer.color_style(MutedRole))
        layout = QVBoxLayout(self)
        layout.addSpacing(24)
        layout.addWidget(self.banner)
        layout.addWidget(self.project)
        layout.addSpacing(8)
        layout.addWidget(self.new_session_button)
        layout.addSpacing(12)
        layout.addWidget(self.rows, 1)
        layout.addWidget(self.hints)
        layout.addSpacing(4)
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
        self.content = ListedModel(model, self.host)
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
        """The welcome leaves the sidebar as the user left it, as Textual's welcome does."""


class TreeItemRows[KeyT](KeyedRows[KeyT]):
    """The shared `KeyedRows` reconciliation over one tree item's children. Qt forgets an
    item's open groups when the item is taken out of the tree, so a reorder reopens them
    where they land."""

    parent: QTreeWidgetItem

    def member_order(self) -> Iterator[QTreeWidgetItem]:
        return (self.parent.child(index) for index in range(self.parent.childCount()))

    def row_attached(self, row: QTreeWidgetItem) -> bool:
        return row.parent() is self.parent or (row.parent() is None and row.treeWidget() is not None
                                               and self.parent is row.treeWidget().invisibleRootItem())

    def mount_row(self, row: QTreeWidgetItem) -> None:
        self.parent.addChild(row)

    def order_rows(self, position) -> None:
        """Move only the lines out of place, each where it belongs, reopening its groups."""
        for index, row in enumerate(sorted(self.member_order(), key=position)):
            if self.parent.child(index) is not row:
                opened = [group for group in row.subtree() if group.isExpanded()]
                self.parent.takeChild(self.parent.indexOfChild(row))
                self.parent.insertChild(index, row)
                for group in opened:
                    group.setExpanded(True)

    def retire_row(self, row: QTreeWidgetItem) -> None:
        self.parent.removeChild(row)


class KeptLines(TreeItemRows[tuple[type, str]]):
    """One tree line's children through one redraw, by kind and key, on the shared
    `KeyedRows`: a line still wanted keeps its item, so a press on it and its open or closed
    group survive the update; a new line joins; the lines no longer wanted go and the rest
    take the drawn order when the redraw closes."""

    def __init__(self, parent: QTreeWidgetItem) -> None:
        self.parent = parent
        self.rows = {(type(line), line.key): line for line in self.member_order()}
        self.wanted: list[tuple[type, str]] = []

    def keep[Row: SidebarItem](self, line: Row) -> Row:
        key = (type(line), line.key)
        kept = self.rows.get(key)
        if kept is None:
            # A new line joins where this redraw has reached, so a steady listing moves nothing.
            kept = self.rows[key] = line
            self.parent.insertChild(len(self.wanted), line)
            line.placed()
        else:
            kept.draw(*line.drawn)
        self.wanted.append(key)
        return kept

    def create_row(self, key):
        raise LookupError(f"{key} was drawn without being kept")

    def group(self, line: SidebarItem) -> KeptLines:
        """``line`` kept, with its own children kept in turn until the group closes."""
        return KeptLines(self.keep(line))

    def close(self) -> None:
        self.reconcile_keys(self.wanted, changed=frozenset())

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
        # One column: a line's text spans the row, as Textual's rows do. A channel line's
        # order control lies over the right end of its first line (`HeaderLineControl`).
        self.setColumnCount(1)
        # The scrollbar is one cell wide, as Textual's sidebar viewport draws it
        # (`scrollbar_size_vertical = 1`): a narrow sidebar keeps its text width.
        cell = self.fontMetrics().averageCharWidth()
        self.setStyleSheet(scheme.styles.generate_tree_widget_style()
                           + f"QScrollBar:vertical {{ width: {cell}px; }}"
                           f"QScrollBar:horizontal {{ height: {cell}px; }}")
        self.setItemDelegateForColumn(0, MultilinePreviewItemDelegate(
            scheme.to_qcolor(scheme.text_primary), scheme.to_qcolor(scheme.text_secondary),
            scheme.to_qcolor(scheme.selection_text), self))
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
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

    def line_width(self, item: SidebarItem) -> int:
        """The text width a line at ``item``'s depth gets: the viewport less the indentation
        its ancestors (and the root's branch) take and the delegate's text inset."""
        depth = int(self.rootIsDecorated())
        parent = item.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        return (self.viewport().width() - self.indentation() * depth
                - 2 * MultilinePreviewItemDelegate.TEXT_INSET_X)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """A new width fits every line's text again."""
        super().resizeEvent(event)
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            for line in root.child(index).subtree():
                line.fit()

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


class HeaderLineControl(QWidget):
    """A channel line's first row: its name, elided before the control that ends the row,
    as Textual's header line ends in its `ChannelSortSegment`. Presses beside the control
    pass through to the tree, so the line still opens."""

    def __init__(self, control: QWidget) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Widget)
        # The name elides; its unread badge follows it and always shows, as Textual's
        # header line draws the title, then `ChannelUnreadSegment`, then the order.
        self.title = ElidedLine("")
        self.badge = QLabel("")
        # Title and badge abut (`#a…●`); one gap separates them from the order.
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.title, 1, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        row.addSpacing(UiGap.tight)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignTop)
        for label in (self.title, self.badge):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def show_title(self, label: str, badge: str) -> None:
        self.title.setText(label)
        self.badge.setText(badge)
        self.badge.setVisible(bool(badge))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class QtChannelGroup(ChannelGroupRows, TreeItemRows[str]):
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
        # Per-member thread rows this group currently shows, by thread key (KeyedRows.rows).
        self.rows: dict[str, ThreadLine] = {}
        # Per-channel sort state, shared with Textual's `ChannelSortChoice` via
        # `SortControlBase`. The Qt widget owns its own menu + write path; Textual
        # renders the same state through a header-row segment. `present` pushes
        # `channel.order` into it so `sort_label` / `sort_tooltip` stay in sync.
        self.sort_choice = QtChannelSortControl(sidebar.window, name)
        # The order sits at the right end of the channel's first line, as Textual's
        # `ChannelSortSegment` ends the header line. `setItemWidget` requires the item
        # to already be in the tree, which both construction paths guarantee.
        row.header = HeaderLineControl(self.sort_choice)
        badge, label, _, _ = row.drawn
        row.header.show_title(label, badge)
        sidebar.setItemWidget(row, 0, row.header)

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
        self.row.present_channel(channel, counts=self.sidebar.window.settings.sidebar.unread_counts)
        # Keep the per-channel sort-control state in sync with the observed order,
        # matching Textual `ChannelGroup.present` (widgets/comms_sidebar.py:141).
        self.sort_choice.update_order(channel.order)
        if previous is None:
            return frozenset()
        return previous.pinned_members ^ channel.pinned_members

    def sync_members(self, changed: frozenset[str]) -> None:
        """Reconcile this channel's thread rows against the model through the shared
        `KeyedRows.reconcile_keys`, as Textual's ChannelGroup does."""
        if self.sidebar.model_state.shows_model():
            self.reconcile_keys(self.member_keys, changed=changed)

    def repaint_members(self, names: frozenset[str]) -> None:
        """Repaint any of this group's shown rows whose thread key is in ``names``.
        Membership changes come through ``sync_members`` instead."""
        if self.sidebar.model_state.shows_model():
            for name in self.rows.keys() & names:
                self.update_row(name, self.rows[name])

    # KeyedRows: which rows exist and how each paints

    def should_mount(self, key: str) -> bool:
        return key in self.sidebar.model_state.shown.threads.rows

    def create_row(self, key: str) -> ThreadLine:
        return ThreadLine(KnownThreadTarget(key, self.sidebar.model_state.shown.threads.rows[key].incarnation))

    def update_row(self, key: str, row: ThreadLine) -> None:
        shown = self.sidebar.model_state.shown
        thread = shown.threads.rows.get(key)
        if thread is None:
            return
        channel = shown.channels.rows.get(self.name)
        row.present_thread(thread, pinned=channel is not None and key in channel.pinned_members,
                           action_status=self.sidebar.window.thread_actions.pending.get(key),
                           counts=self.sidebar.window.settings.sidebar.unread_counts)

    @property
    def parent(self) -> ChannelLine:
        """TreeItemRows: the channel's own line holds its thread lines."""
        return self.row


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
            self.window.channel_sort.update_order(model.observation.channel_order())
            self.window.workspace_sessions.home.present(model)
            self.window.paint_tabs()
            # Register every working thread row with the shared pulse animator
            # so its text foreground sine-waves while the agent is busy — Qt's
            # port of Textual's NAME_WAVE effect
            # (ui_theme.effects.NAME_WAVE wired into comms_sidebar.ThreadRow).
            working_names = {name for name, thread in model.threads.rows.items()
                             if thread.status.is_working()}
            working_items: list[QTreeWidgetItem] = []
            if working_names:
                stack = [self.invisibleRootItem()]
                while stack:
                    node = stack.pop()
                    for index in range(node.childCount()):
                        child = node.child(index)
                        stack.append(child)
                        if isinstance(child, ConversationRow) and child.key in working_names:
                            working_items.append(child)
            self.window.thinking_animator.set_working_items(working_items)

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
        top.keep(NewSessionRow())
        threads = model.threads.rows
        matches = self.filter.matches
        pending = self.window.thread_actions.pending
        counts = self.window.settings.sidebar.unread_counts
        for name, channel in model.channels.rows.items():
            # A channel stays visible if its name matches OR any of its member thread
            # names do; hiding a channel whose only match is a buried thread would also
            # hide the thread. The group opens whichever path kept it.
            members_shown = [m for m in channel.members if matches(m)]
            if not matches(name) and not members_shown:
                continue
            pinned_members = channel.pinned_members
            with top.group(ChannelLine.of(name, channel, counts=counts)) as group:
                for member in members_shown:
                    group.keep(ThreadLine.of(member, threads[member], pinned=member in pinned_members,
                                             action_status=pending.get(member), counts=counts))

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
            group.sort_choice.update_order(group.channel.order)
            # Index the thread children the wholesale redraw just placed.
            for child_index in range(item.childCount()):
                child = item.child(child_index)
                if isinstance(child, ConversationRow):
                    group.rows[child.key] = child
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
    """Where the bus this window reads lives, as its connection names it, prefixed with
    the agent binding's `welcome_prefix` so the line reads the same way Textual's does
    at `screens/welcome.py:256` — `f"{agent_binding.welcome_prefix}{location}"`. A Qt
    client is always remote, so its own launch directory (on the phone, /data/data/…/app)
    says nothing about the Core it shows; the connection's location does.

    `welcome_prefix` is empty for `NoAgent` so a connection without an attached agent
    reads as before. With `AgentAttached`, the line reads e.g. `claude · <location>`."""

    def __init__(self, window: QtToadApp) -> None:
        location = window.coordination_access.connection.location
        prefix = window.agent_binding.welcome_prefix
        super().__init__(f"{prefix}{location}")
        self.setToolTip(f"{prefix}{location}")


class ConversationView(QtViewSettings, WorkingStatusOwner, ComposerStatus, CategorySelection, ConversationSettingsOwner, ConversationViewNavigation, JumpsHistory, MenuConversation, Page, SessionScope, QtSubmissionView, WireView,
                       QtHistoryNotifications, ComposerHost, WorkspaceHosted, FlashHost, QWidget,
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
        # This view owns which message categories its transcript shows (`CategorySelection`);
        # the history reads it through `selected_categories` and the comms panel writes it.
        self.visible_categories = all_categories()
        # The fragment the viewer most recently long-pressed, if any; menu commands read
        # it to know which block they act on.
        self.held_fragment: QtWireFragment | None = None
        label = entry.unobserved_tab().label()
        self.messages = QtHistoryWindow(app.renderer, self)
        self.messages.block_menu_requested.connect(self.open_block_menu)
        self.message_history = QtConversationHistory(self.messages, self, app)
        source = app.source()
        # WireSource IS a BusQueueSource (client/history.py:372); storing it on
        # self.queue_source lets BusSubmissions.queue_evidence read pending/queued/held
        # state the same way CommsChatView does (widgets/comms_chat.py:124-129).
        wire = WireSource(
            source.root, self.conversation, source.project, entry.viewer, self.configuration_state.fields.ui.message_style(),
            access=app.coordination_access, core=source.core, fragments=QtWireFragment)
        self.queue_source = wire
        self.message_history.initialize_source(wire)
        self.message_history.observe_source()
        # Textual's `CommsChatView.compose`: the flash under the window, the prompt (its
        # info bar carries the thread status), then who is here, under the prompt.
        self.feedback = QtFlash(app, app.renderer)
        # Textual's `CommsChatView.throbber_above`: the sweep painting `working()` — an idle
        # turn (no agent on a wire view), the peer's observed row, or the first page loading.
        self.turns = ConversationTurn(lambda owner: self.sync_working(), lambda: NoAgentConnection().presentation.turns)
        self.agent_activity = QtObservedSweep(self.working, renderer=app.renderer)
        self.composer = self.conversation.prompt(self)
        self.composer.labelled(label)
        self.activity = tuple(self.conversation.compose_activity(self))
        # The inline consent prompt ("did you mean it?", edit/clear confirmations) — hidden
        # until the conversation asks, mounted below the composer so the picks sit where
        # the next message would be typed, mirroring Textual's Prompt.ask.
        self.question = QtQuestion(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.feedback)
        layout.addWidget(self.agent_activity)
        layout.addWidget(self.composer)
        layout.addWidget(self.question)
        # Under the prompt, not over it: who is here is reference (Textual's
        # `CommsChatView.compose` yields the kind's activity after the prompt).
        for line in self.activity:
            layout.addWidget(line)
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
        self.refresh_thread_status()
        self.sync_working()
        label = self.conversation.label(source.references())
        self.composer.labelled(label)
        read_only = await asyncio.to_thread(self.conversation.read_only, source.core)
        await self.refresh_composer(read_only)
        self.thread_status = await self.conversation.status_text(source, read_only=read_only)
        self.composer.show_status(self.composed_status())
        await self.conversation.update_mentions(self, source)

    # The kind's composer and activity (ConversationActivity)

    def status_thread(self) -> StatusThread:
        return self.conversation.status_thread(self.app.source().root, self.app.coordination_access)

    def history_loading(self) -> bool:
        """As Textual's `CommsChatView`: the wire history is reading its first page."""
        return self.message_history.reading

    def sync_working(self) -> None:
        self.agent_activity.sync()

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
        self.thread_activity = PeerActivity(self.app, self.app.renderer, peer, self.sync_working)
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
        self.feedback.flash(text)

    def flash_success(self, text: str) -> None:
        self.feedback.flash(text, style=SuccessTone.declared_name)

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

    def submit(self, text: TypedText, action: SubmitInputAction) -> None:
        """A bus message is delivered as soon as it is sent, so every action sends it; an
        empty send-now has no held queue here to flush."""
        if text.text.strip():
            self.app.run_operation(ConversationSubmission, partial(self.start_send, text))

    async def start_send(self, text: TypedText) -> None:
        if await CommandCatalog.execute(text.text, self):
            return
        root = self.app.source().root
        await self.submissions.start_bus(text, ChannelDestination(root, self.conversation, self)).prepare()

    def categories_changed(self) -> None:
        self.message_history.apply_filter()

    @property
    def configuration_identity(self):
        return self.entry.identity

    @property
    def configuration_settings(self):
        return self.app.saved_settings

    @property
    def navigation_project(self):
        return self.app.project_dir

    @property
    def coordination_root(self) -> str:
        return self.entry.key.root

    @property
    def thread_identity(self):
        """The viewer on this conversation's wire, as Textual's `CommsScreen` acts."""
        return self.entry.viewer_identity


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
        view.close_configuration()
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
        # Until a conversation reads Core's display references, bodies link the project's files.
        self.renderer = QtLineRenderer(scheme, LinkContext(project.path.resolve(), ProjectReferences()),
                                       self.settings.diff.marks)
        # One shared animator pulses every sidebar row whose thread is working —
        # Qt's equivalent of Textual's per-row NAME_WAVE effect
        # (ui_theme.effects.NAME_WAVE / widgets/comms_sidebar.ThreadRow). The
        # sidebar's `present` loop registers the current working rows after each
        # redraw; the animator's one timer drives the pulse for every registered
        # row so the sine phase stays shared across the sidebar.
        self.thinking_animator = QtThinkingAnimator(scheme, parent=self)
        # One background task per transfer kind, cancelled + replaced when the same
        # kind is submitted again (Qt analog of Textual's run_worker exclusive=True).
        # Populated by `start_transfer_task`; the dict is the live registry.
        self._transfer_tasks: dict[str, "asyncio.Task[None]"] = {}
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
        self.channel_sort = QtChannelListSort(self)
        self.sidebar_search = QtSidebarShell(
            self.sidebar.filter,
            QtSidebarPanels(self.sidebar_state, (QtPanelEntry(CHANNELS_PANEL, self.sidebar, (self.channel_sort,), CHANNELS_PANEL.title),)),
            parent=self)
        self.thread_pane = ThreadSettingsPane(self, parent=self,
                                              project_path=self.project_dir.path)
        # The pages and both sidebars live in one chrome that places them where the shared
        # SidebarChromeArrangement resolves them, as Textual's WorkspaceChrome does: a docked
        # sidebar pushes the pages, a floating one lies over them, a folded one is its strip.
        # Parent self throughout: a parentless QWidget on Qt-for-Android becomes its own
        # top-level window with its own EGL surface (PR #1885's SIGABRT).
        self.chrome = QtWorkspaceChrome(self.sidebar_layout, self.workspace_sessions.pages,
                                        available=self._pane_available, parent=self)
        self.channels_side = QtSideBar(
            self.sidebar_layout, ChannelsSidebarPlacement, self.sidebar_search,
            heading=partial(self._pane_heading, ChannelsSidebarPlacement),
            toggled=partial(self.toggle_pane, ChannelsSidebarPlacement),
            arranged=self.rearrange_sidebars, parent=self.chrome)
        self.thread_side = QtSideBar(
            self.sidebar_layout, ThreadSidebarPlacement, self.thread_pane,
            heading=partial(self._pane_heading, ThreadSidebarPlacement),
            toggled=partial(self.toggle_pane, ThreadSidebarPlacement),
            arranged=self.rearrange_sidebars, parent=self.chrome)
        self.chrome.sidebars = (self.channels_side, self.thread_side)
        styles = self.theme.color_scheme.styles
        for side in self.chrome.sidebars:
            side.setStyleSheet(styles.generate_sidebar_pane_style() + styles.generate_sidebar_bar_style())
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
        bar.setSpacing(UiGap.tight)
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
        # Bus switcher: inline overlay panel for the hamburger "Switch bus" entry.
        # Registered as a `BusListing` so `tailnet_answered` routes answers to it
        # while shown (same shape as Welcome, which is always registered).
        from toad.qt.bus_switcher import QtBusSwitcher
        # Welcome is always a BusListing; the switcher registers/deregisters
        # itself while shown so answers reach both.
        self._bus_listings: list[BusListing] = [self.workspace_sessions.home]
        self.bus_switcher = QtBusSwitcher(self)
        chrome_layout.addWidget(self.bus_switcher)
        # Paste surface for the bus-connect remediation ("Paste a profile" option on the
        # BusConnectDecision menu). Inline QFrame child of the window, not a QDialog —
        # same EGL rationale as QtMenu: a top-level popup needs its own surface and
        # deadlocks the compositor on Pixel 8a.
        self.profile_paste_panel = QtProfilePastePanel(self)
        chrome_layout.addWidget(self.profile_paste_panel)
        chrome_layout.addLayout(bar)
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        # The navigation bar sits above or below the conversation row as the shared
        # `ui.navigation_bar` setting places it — the one Textual's WorkspaceHeader reads.
        for widget in self.settings.ui.navigation_bar.around(chrome, self.chrome):
            layout.addWidget(widget, 1 if widget is self.chrome else 0)
        self.fit_screen()
        # The channels sidebar opens as the shared `sidebar.hide` setting says, as Textual's
        # ChannelsSidebar mounts; the thread sidebar starts folded, as Textual's ThreadSidebar.
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, self.settings.sidebar.hide)
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
        badge = self.settings.sidebar.unread_counts.badge
        for tab in self.session_navigation.tabs:
            self.tabs.addTab(tab.label() + tab.unread_suffix(badge))
        self.tabs.blockSignals(False)
        self.mark_current()

    def mark_current(self) -> None:
        modes = [tab.mode_name for tab in self.session_navigation.tabs]
        mode = self.selected_mode
        self.tabs.setCurrentIndex(modes.index(mode) if mode in modes else -1)
        self.present_panes()

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
        """The viewed tab's title, as Textual's `SideBar.heading` reads it."""
        mode = self.selected_mode
        return (tab.title for tab in self.session_navigation.tabs if tab.mode_name == mode)

    def _bind_thread_pane(self) -> None:
        """The thread's settings follow the selected page: a conversation, or the welcome,
        which is a `NoConversationView`."""
        self.thread_pane.bind(self.workspace_sessions.selected)

    def present_panes(self) -> None:
        """Draw both sidebars from the one layout and place them; the thread's sidebar is
        presented only while a conversation is open."""
        self._bind_thread_pane()
        for side in self.chrome.sidebars:
            side.present()
        self.chrome.arrange()

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
        """Route the answer to every registered `BusListing`. The welcome is always
        registered; the bus switcher registers itself while shown. Shared
        `BusListing.shown_in` dispatch means Qt needs no per-listing branch."""
        for listing in tuple(self._bus_listings):
            answer.shown_in(listing)

    def register_bus_listing(self, listing: BusListing) -> None:
        """Called by `QtBusSwitcher.show_switcher` so tailnet answers reach it while
        shown. Welcome is registered at construction; the switcher comes and goes."""
        if listing not in self._bus_listings:
            self._bus_listings.append(listing)

    def deregister_bus_listing(self, listing: BusListing) -> None:
        if listing in self._bus_listings:
            self._bus_listings.remove(listing)

    def open_bus_switcher(self) -> None:
        """Hamburger `OpenBusAction` hook: show the inline Qt switcher instead of
        Textual's `BusChoices` modal. The shared `BusListing` contract gives the
        switcher the same rows, prompt text (`BusSwitcherPrompt`) and ask-tailnet
        behavior Textual has; the Qt layer is just rendering + input wiring."""
        self.bus_switcher.show_switcher()

    async def close_native_views(self) -> None:
        self.shortcuts.close()
        await self.session_navigation.close_views()

    async def close_rendering(self) -> None:
        await self.preparation.aclose()

    async def open_keymap_browser(self) -> None:
        """Qt override of `ClientApplication.open_keymap_browser`. Opens the
        shared-UX `QtKeymapScreen` modal; both frontends consume the same
        `KeymapBrowserState` so the browser logic lives once in
        `toad.client.keymap_browser`."""
        from toad.keymap import KeyInvocationId
        from toad.qt.keymap_screen import QtKeymapScreen
        focused: frozenset[KeyInvocationId] = frozenset()
        dialog = QtKeymapScreen(self, focused)
        dialog.show()

    async def edit_settings(self) -> None:
        """Qt override of `ClientApplication.edit_settings`: the settings screen both
        frontends inherit (`SettingsEditing`), drawn in Qt; it saves on close through
        `ClientApplication.settings_closed`, as Textual's does."""
        from toad.qt.settings_screen import QtSettingsScreen
        dialog = QtSettingsScreen(self, self)
        dialog.show()

    async def open_team_board(self) -> None:
        """Qt override of `ClientApplication.open_team_board`. Opens the
        shared-UX `QtTeamBoardScreen`; both frontends subscribe to the same
        `TeamHudChanged` / `TeamHudFailed` Core events and route them through
        `toad.client.team_board.TeamBoardState` for identical filtering."""
        from toad.qt.team_board_screen import QtTeamBoardScreen
        dialog = QtTeamBoardScreen(self)
        dialog.show()

    def open_transfer(self, kind) -> None:
        """Qt override of `ClientApplication.open_transfer`: the Qt member of the shared
        transfer-form family that composes `kind`; its submit calls
        `start_transfer_task(request, selected)`, so one task per kind supersedes a repeat."""
        from toad.qt.transfer import QtTransferDialog
        access = self.coordination_access
        selected = access.selected(access.observation.observed().root)
        QtTransferDialog.for_kind(kind)(self, selected, parent=self).show()

    def start_transfer_task(self, request, selected) -> None:
        """Qt analog of Textual's `run_worker(..., exclusive=True)`: cancel any
        running task tagged with this kind's declared name, then schedule the
        new one on the running loop. Keeps the shared `TransferRequest.execute`
        on the UI thread's event loop (its internal `preparation.run_thread`
        hop keeps the CPU work off the GIL)."""
        import asyncio
        existing = self._transfer_tasks.get(type(request).declared_name)
        if existing is not None and not existing.done():
            existing.cancel()
        task = asyncio.ensure_future(request.execute(self, selected))
        self._transfer_tasks[type(request).declared_name] = task

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
        self.open_target(row.target)

    def open_target(self, target: NavigationTarget) -> None:
        """Open a thread or channel as its sidebar row does: from a row, or a link naming it.
        The shared navigator applies the request (`TargetOpen`), from home."""
        self.session_navigation.events.publish(session_requests.TargetOpen(target))

    @property
    def selected_mode(self) -> str:
        return self.workspace_sessions.selected.mode

    @property
    def welcome_hints(self) -> str:
        """Qt (touch) override of the gesture hint line shown under the welcome
        rows. Textual's version carries keyboard shortcuts; Qt's carries touch
        gestures since Qt-on-Android has no keyboard. Called by both Welcome
        implementations through `self.app.welcome_hints`."""
        return (
            "Tap thread to open · long-press for menu · swipe > for sidebar\n"
            "≡ for menu · ← → navigate history"
        )

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
        self.close_session(self.session_navigation.tabs[index].mode_name)

    def move_index(self, start: int, end: int) -> None:
        """A tab dragged from one place in the bar to another: it moves past the tab it
        displaced in the shared order, which also holds saved tabs this window has not
        opened, and the bar draws that order again."""
        tabs, order = self.session_navigation.tabs, self.tab_order.names
        moved, displaced = tabs[start], tabs[end].identity
        self.session_navigation.events.publish(session_requests.SessionMove(
            moved.mode_name, order.index(displaced) - order.index(moved.identity)))

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
