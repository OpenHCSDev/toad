"""The Qt application: the shared client application drawn as Toad's tabs over the
conversations you open, and its sidebar of channels and threads behind the bar above them.

Tabs open, switch and close through the shared SessionNavigation, as Textual's do: a
sidebar row is the shared history route, each tab is the shared conversation entry, and
QtWorkspaceViews draws its view, a Qt ConversationView.
"""

from __future__ import annotations

import asyncio
import os
import shiboken6
from contextlib import contextmanager
from time import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import ClassVar, Self
from functools import partial
from pathlib import Path

from agent_comms.messaging.channel_targets import ChannelSelection, NoChannel, OneChannel
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.projects.checkouts import Checkout
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.transport.request import CoreAccess
from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel
from formbridge.operations import OperationKind
from PySide6.QtCore import QEvent, QFileSystemWatcher, QMargins, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPalette, QScreen, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QScroller,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from toad.keymap import KeyInvocationId
from toad.qt.finger_press import FingerPress
from toad.qt.mailbox_view import QtMailboxView
from toad.qt.opening_view import QtOpeningSessionView
from toad.qt.tap_flash import QtPushButton, QtTextButton
from ui_theme.scheme import (
    AlternateRowToneColour,
    ColourScheme,
    PrimaryColour,
    SidebarToneColour,
    ThemeColour,
)
from ui_theme.wal import WalFile
from pyqt_reactive.theming import ColorScheme

from toad.client.theme_tones import (
    ScrollbarTones,
    WorkspaceTabTones,
)

from toad.client.pending import ActionRunning, awaited
from toad.app_core import CorePrewarm
from toad.client.application import ACTIVE_PRESENCE, ApplicationPresence, ClientApplication
from toad.qt.workspace_frame import QtWorkspaceFrame, QtWorkspaceHosted
from toad.qt.widget_animation import QtAnimationClock, frame_interval
from toad.workspace_frame import WorkspaceFrame
from toad.client.session_scope import NoConversationView
from toad.client.application_actions import (
    ApplicationAction,
    MenuActionRun,
    NewSessionAction,
    NewSessionControl,
    ResetZoomAction,
    ZoomInAction,
    ZoomOutAction,
)
from toad.client.bus_connect import BusConnectDecision
from toad.client.bus_selection import (
    BusAddressEntry,
    BusChoice,
    BusListing,
    BusPickerHost,
    PickerRow,
    TailnetAnswer,
)
from toad.client.bus_submission import SubmissionView
from toad.submission_queue import NoQueueSource, QueueSource
from toad.client.connection import (
    CoreConnection,
    FailedObservation,
    Observing,
)
from toad.client.conversation import ConversationKind
from toad.client.conversation_capabilities import ConversationSource
from toad.client.history import WireSource, WireView
from toad.client.history_entry import HistorySessionEntry
from toad.application_lifetime import ApplicationStart
from toad.client import platform as toad_platform
from toad.client.platform import host
from toad.client.line_blocks import MutedRole
from toad.qt.banner import Banner
from toad.client.welcome import WelcomeLocation
from toad.client.sidebar_models import UnpaintedChannel
from toad.client.sidebar_lines import (
    BusChoiceLine, DetailedLine, FittedRowTree, HeaderLine, LineMenuTree, MemberGroupLine, RowTree, SidebarStatusLine, TargetLine,
    WelcomeSectionLine,
)
from toad.keyed_rows import KeyedRows
from toad.setting_choices import UnreadCount
from toad.sidebar_rows import ChannelLineText, ChannelRowFace, ThreadLineText, ThreadRowFace
from toad.client.referenced_core import ReferencedCore
from toad.client.session_scope import NoSessionOrigin, SessionOrigin, SessionScope
from toad.client.subscribers import SidebarSubscriber
from toad.sidebar_changes import AllSidebarRows, SidebarChange
from toad.sidebar_contracts import (
    ChannelGroupRows,
    FindsOpenViews,
    GroupedSidebar,
    NavigationRefresh,
)
from contextlib import nullcontext
from toad.client.sidebar_state import SidebarStateMachine
from toad.client.tab_identity.kinds import CommsTab
from toad.constants import WELCOME
from toad.core import session_requests
from toad.core.events import CoordinationObserved, ExternalTranscriptChanged, TabHistoryChanged
from toad.launch_binding import AgentBinding, NoAgent
from toad.launch_opening import LaunchOpening, NoLaunchOpening
from toad.navigation_context import HomeNavigation, NavigationOwner
from toad.session_navigation import TabElement
from toad.client.session_scope import HomeSessionOrigin
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import PanelSpec
from toad.navigation_context import ConversationViewNavigation
from toad.navigation_target import (
    HistoryRouted, KnownThreadTarget, NavigationTarget, channel_target,
)
from toad.qt.action_shortcuts import ActionKeys
from toad.qt.activity import PeerActivity
from toad.qt.command_form import WindowCommandOrigin
from toad.qt.composer import ChannelComposer, Composer, ComposerEditor, MessageComposer
from toad.qt.conversation import QtConversation
from toad.qt.host import QtCommsHost, ScreenWideWindow
from toad.qt.history import QtWireHistory, RowPictures
from toad.qt.transcript_fragments import QtWireFragment
from toad.menus import MenuCommand
from toad.client.menu_entry import MenuEntry, strip_menu_markup as _strip_menu_markup_shared
from toad.qt.menu import QtMenu, platform_input
# Imported at load, not in open_transfer: this declares the Transfer members the shared
# TransferMenuAction lists, so the menu offers Export and Import as Textual's does.
from toad.client.transfers import Transfer
from toad.qt.transfer import QtTransferDialog
from toad.qt.channel_sort import QtChannelListSort, QtChannelSortControl
from toad.motion import animations_enabled
from toad.qt.name_wave import PaintedRowTone, QtClockedWave, QtNameWaveDelegate, QtSessionTabBar
from toad.qt.sidebar_panel import QtPanelEntry, QtSidebarPanels, QtSidebarShell
from toad.qt.view_settings import capability_widgets
from toad.qt.attention import QtWindowAttention
from toad.qt.theme import offered_schemes
from toad.client.view_layout import LayoutFollower
from toad.qt.paste_profile import QtProfilePastePanel
from agent_comms.messaging.display_references import ProjectReferences
from toad.markdown_links import LinkContext
from toad.qt.float_layer import QtFloatLayer
from toad.qt.lines import QtLineRenderer
from toad.qt.goal import QtGoalBar
from toad.qt.placement import ThreadSettingsPane
from toad.qt.side_bar import QtSideBar, QtWorkspaceChrome
from toad.qt.interactive_dialog import QtInteractiveDialog
from toad.qt.question import QtQuestion
from toad.session_host import SessionEntries, SessionNavigator, WorkspaceViews
from toad.sidebar_layout import CHANNELS_PANEL
from toad.sidebar_placement import (
    ChannelsSidebarPlacement,
    SidebarPlacement,
    ThreadSidebarPlacement,
)
from toad.status_thread import StatusThread
from toad.target_commands import TargetContext
from toad.work_preparation import PreparationRuntime


def _scrollbar_qss(
    renderer: QtLineRenderer,
    *,
    selector: str = "QScrollBar",
    scale: int = 100,
    fixed_thickness: bool = True,
) -> str:
    """Shared scrollbar stylesheet matching Textual's `$scrollbar-*` tokens across Qt."""
    track = renderer.theme(ScrollbarTones.track_colour)
    thumb = renderer.theme(ScrollbarTones.thumb_colour)
    hover = renderer.theme(ScrollbarTones.hover_colour)
    active = renderer.theme(ScrollbarTones.active_colour)
    min_thumb = scaled_px(24, scale)
    size_qss = ""
    if fixed_thickness:
        thick = scaled_px(12, scale)
        size_qss = (
            f"{selector}:vertical {{ width: {thick}px; }}"
            f"{selector}:horizontal {{ height: {thick}px; }}"
        )
    return (
        f"{selector}:vertical, {selector}:horizontal {{"
        f" background-color: {track}; border: none; margin: 0px; }}"
        + size_qss
        + f"{selector}::handle:vertical, {selector}::handle:horizontal {{"
        f" background-color: {thumb}; border: none; border-radius: 0px;"
        f" min-width: {min_thumb}px; min-height: {min_thumb}px; }}"
        f"{selector}::handle:vertical:hover, {selector}::handle:horizontal:hover {{"
        f" background-color: {hover}; }}"
        f"{selector}::handle:vertical:pressed, {selector}::handle:horizontal:pressed {{"
        f" background-color: {active}; }}"
        f"{selector}::add-line:vertical, {selector}::sub-line:vertical,"
        f"{selector}::add-line:horizontal, {selector}::sub-line:horizontal {{"
        f" width: 0px; height: 0px; background-color: {track}; border: none; }}"
        f"{selector}::add-page:vertical, {selector}::sub-page:vertical,"
        f"{selector}::add-page:horizontal, {selector}::sub-page:horizontal {{"
        f" background-color: {track}; border: none; }}"
        f"QAbstractScrollArea::corner {{ background-color: {track}; }}"
    )


@dataclass(frozen=True)
class ObservedSource(ConversationSource):
    """The observed Core's reads, in the project this window views."""

    core: CoreAccess
    root: Path
    project: Checkout


class SidebarItem(DetailedLine, PaintedRowTone, QTreeWidgetItem):
    """One line of the sidebar tree, the shared `DetailedLine` (Textual's `DetailedRow`):
    its title after its status prefix, its detail indented under it; a tap activates it."""

    key: str
    animation: object | None = None
    drawn: tuple[str, str, str, str] = ("", "", "", "")
    _painted_tone: QBrush | None = None
    _fitted_layout: tuple[str, str, str] | None = None
    row_tones: ClassVar[tuple[type[ThemeColour], type[ThemeColour]]] = (
        SidebarToneColour,
        AlternateRowToneColour,
    )

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
        return self.status_prefix(badge), label

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
            summary = metrics.elidedText(summary, right,
                                         max(1, width - metrics.horizontalAdvance(self.detail_text(""))))
        fitted = (name, prefix, summary)
        if fitted == self._fitted_layout:
            return
        self._fitted_layout = fitted
        self.setData(0, LAYOUT_ROLE, StyledTextLayout(
            name=Segment(name), status_prefix=prefix, detail_line=summary, multiline=True))

    def placed(self) -> None:
        """A new line fits its text to the tree it just joined."""
        self.fit()

    def take(self, line: SidebarItem) -> None:
        """A redraw's fresh ``line`` for this kept one: draw its text here."""
        self.draw(*line.drawn)

    def retired(self) -> None:
        """The line leaves the tree; a line running nothing has nothing to stop."""

    def wave_span(self) -> tuple[int, int] | None:
        """The title characters the name wave covers now; None for a line that is not
        waving (`ConversationRow` waves while its thread works)."""
        return None

    def wave_running(self) -> bool:
        """Whether the line's name waves now: only a conversation's line ever does
        (`ConversationRow`, whose wave answers this before the line does)."""
        return False

    def band_drawn(self) -> tuple[int, int] | None:
        """The band's cells the line draws (`NameWave.band_drawn`): none, for a line that
        never waves."""
        return None

    def subtree(self) -> Iterator[SidebarItem]:
        """This line and every line under it."""
        yield self
        for index in range(self.childCount()):
            yield from self.child(index).subtree()

    def visible_subtree(self) -> Iterator[SidebarItem]:
        """This line and every line currently reachable through expanded groups."""
        yield self
        if self.isExpanded():
            for index in range(self.childCount()):
                yield from self.child(index).visible_subtree()

    def activate(self, window: QtToadApp) -> None:
        """A group line opens and closes its group."""
        self.setExpanded(not self.isExpanded())

    def activate_in_switcher(self, switcher, window: QtToadApp) -> None:
        """Activation inside `QtBusSwitcher`: section headers expand/collapse without closing."""
        self.activate(window)

    async def menu_entries_in(self, listing: Welcome) -> tuple[MenuEntry, ...]:
        """What `HeldRowMenu` offers for this line: nothing, for most lines."""
        return ()

    def update_status_in(self, root: QTreeWidgetItem, text: str | None) -> bool:
        """If this item is the sidebar's status row, update or remove it and return True."""
        return False

    def register_group_member(self, rows: dict[str, ConversationRow]) -> None:
        """Index this child row into its channel group's lookup when it is a conversation row."""

    def rebind_group_into(
        self,
        sidebar: Sidebar,
        channel_models: Mapping[str, ChannelRowModel],
        previous: dict[str, QtChannelGroup],
        rebuilt: dict[str, QtChannelGroup],
    ) -> None:
        """Rebind this top-level row's channel group into `rebuilt` when it is a channel row."""

    def channel_selection(self) -> ChannelSelection:
        """The channel a line listed under this one is read in: none, for most lines."""
        return NoChannel()


class SidebarSection(MemberGroupLine, SidebarItem):
    """A group of rows with a title, such as Threads: the shared `MemberGroupLine`
    (Textual's `SidebarGroup`), its members the item's children."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.key = title
        self.draw("", title, "", "")

    @property
    def members_open(self) -> bool:
        return self.isExpanded()

    def show_members(self, shown: bool) -> None:
        self.setExpanded(shown)

    def activate(self, window: QtToadApp) -> None:
        self.toggle_members()


class OpensExpandedItem(SidebarItem):
    """A sidebar item whose shared model owns whether it starts expanded (`opens_expanded`)."""

    def placed(self) -> None:
        super().placed()
        self.setExpanded(self.opens_expanded())


class OpenSection(WelcomeSectionLine, SidebarSection, OpensExpandedItem):
    """A titled section of rows that are not the sidebar model's (the buses, in the sidebar
    while it holds the window and in the bus switcher): open as the shared sidebar state says
    (`WelcomeSectionLine`), so it stays as the reader left it however often it is drawn
    again."""

    @property
    def section_title(self) -> str:
        return self.key

    @property
    def sidebar_state(self):
        return self.treeWidget().window.sidebar_state


class StatusSection(SidebarStatusLine, SidebarSection):
    """The status line at the top of the sidebar (the shared `SidebarStatusLine`, Textual's
    `SidebarStatus`): an observation status (`Connecting…`, `Behind`) or why the bus could
    not be read, its first line the title and the rest under it. Its fixed key keeps it
    across sibling-row updates."""

    def __init__(self, text: str) -> None:
        title, detail = self.status_rows(text)
        super().__init__(title)
        self.key = SidebarStatusLine.key
        self.draw("", title, detail, text)

    def update_status_in(self, root: QTreeWidgetItem, text: str | None) -> bool:
        if text is None:
            root.takeChild(root.indexOfChild(self))
        else:
            title, detail = self.status_rows(text)
            self.draw("", title, detail, text)
        return True


class ConversationRow(QtClockedWave, TargetLine, OpensExpandedItem):
    """A row that opens its target through the target's own polymorphic `open(context)`.

    `target` is a `NavigationTarget` (not specifically a `HistoryRouted`) because threads
    open via `KnownThreadTarget` → `thread_navigation.open` → `MailboxTab` → agent-bound
    view, while channels open via `channel_target()` → `session_navigation.history` →
    `CommsTab` → wire view. One row class, two destinations; the target picks.
    """

    busy = False
    """Whether the line's thread works: the line then waves (`NameWave`)."""

    def __init__(self, target: NavigationTarget) -> None:
        super().__init__()
        self.key = target.name
        self.target = target

    def placed(self) -> None:
        """A new channel line opens as its target opens by default (the feed does), as the
        Textual sidebar's ChannelGroup does; a working thread's line starts waving."""
        super().placed()
        self.follow_activity(self.busy)

    def take(self, line: SidebarItem) -> None:
        super().take(line)
        self.busy = line.busy
        self.follow_activity(self.busy)

    def retired(self) -> None:
        self.stop_wave()

    # NameWave, on the app's clock; the row is the animation's target.

    def wave_clock(self):
        return self.treeWidget().window.animation_clock

    def wave_visible(self) -> bool:
        tree = self.treeWidget()
        if tree is None or not tree.isVisible():
            return False
        rect = tree.visualItemRect(self)
        return not rect.isEmpty() and tree.viewport().rect().intersects(rect)

    def repaint_wave(self) -> None:
        tree = self.treeWidget()
        if tree is not None:
            rect = tree.visualItemRect(self)
            if not rect.isEmpty():
                tree.viewport().update(rect)

    def wave_cells(self) -> tuple[int, int] | None:
        """The band's cells over the line's width in cells, as Textual's row paints it."""
        tree = self.treeWidget()
        if tree is None:
            return None
        return self.band_cells(self.wave_frame(), tree.line_width(self) // tree.char_width())

    def activate(self, window: QtToadApp) -> None:
        window.open_row(self)

    @property
    def menu_tree(self) -> ConversationRows:
        return self.treeWidget()

    async def menu_entries_in(self, listing: Welcome) -> tuple[MenuEntry, ...]:
        return await self.menu_entries()

    def register_group_member(self, rows: dict[str, ConversationRow]) -> None:
        rows[self.key] = self

    def rebind_group_into(
        self,
        sidebar: Sidebar,
        channel_models: Mapping[str, ChannelRowModel],
        previous: dict[str, QtChannelGroup],
        rebuilt: dict[str, QtChannelGroup],
    ) -> None:
        name = self.key
        if name not in channel_models:
            return
        group = previous.get(name)
        if group is None or group.row is not self:
            group = QtChannelGroup(sidebar, name, self)
        else:
            badge, label, _, _ = self.drawn
            self.header.show_title(label, badge)
            group.rows = {}
        group.channel = channel_models[name]
        group.sort_choice.update_order(group.channel.order)
        for child_index in range(self.childCount()):
            self.child(child_index).register_group_member(group.rows)
        rebuilt[name] = group

    def listed_channel(self) -> ChannelSelection:
        """The channel this line is listed under, as Textual's sidebar selection names it."""
        parent = self.parent()
        return parent.channel_selection() if parent is not None else NoChannel()


class ThreadLine(ThreadRowFace, ConversationRow):
    """A thread's line: the shared thread line text (`ThreadRowFace`) in the tree's two
    rows. It opens as a `KnownThreadTarget`, carrying the birth, as Textual's ThreadRow does."""

    @classmethod
    def of(cls, name: str, thread, *, pinned: bool, action_status: str | None,
           counts: type[UnreadCount]) -> ThreadLine:
        line = cls(KnownThreadTarget(name, thread.incarnation))
        line.present_thread(thread, pinned=pinned, action_status=action_status, counts=counts)
        return line

    def present_thread(self, row, *, pinned: bool, action_status: str | None, counts) -> None:
        self.busy = self.thread_busy(row, action_status)
        super().present_thread(row, pinned=pinned, action_status=action_status, counts=counts)
        if self.treeWidget() is not None:
            self.follow_activity(self.busy)

    def show_thread_text(self, text: ThreadLineText) -> None:
        self.draw(text.badge, text.pin + text.name, text.detail, text.tooltip)


class ChannelEntry(ChannelRowFace, ConversationRow):
    """A channel's line: the shared channel line text (`ChannelRowFace`)."""

    def channel_selection(self) -> ChannelSelection:
        return OneChannel(self.target_name)

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


class SelectedChannelLine(ChannelLine):
    """The selected channel's row in its active bar under the composer: starts collapsed as
    one compact row, and tapping it toggles its member tree instead of reopening the tab
    already open."""

    def opens_expanded(self) -> bool:
        return False

    def activate(self, window: QtToadApp) -> None:
        self.setExpanded(not self.isExpanded())


class NewSessionRow(NewSessionControl, SidebarItem):
    """The Channels sidebar's first line, as Textual's `NewSessionButton`: a tap starts what
    the shared `NewSessionControl` says (this launch's session while no tab is shown, a thread
    in the selected project beside one)."""

    key = NewSessionControl.label

    def __init__(self) -> None:
        super().__init__()
        self.draw("", self.label, "", "Start a thread in the selected project")

    def activate(self, window: QtToadApp) -> None:
        window.run_operation(MenuActionRun, partial(self.start_session, window))


class BusRow(BusChoiceLine, SidebarItem):
    """A bus the welcome lists (the shared `BusChoiceLine`, Textual's `BusOption`): a tap
    does what its choice says: switch onto a held bus, or ask a tailnet peer for a profile
    to its bus."""

    def __init__(self, choice: PickerRow) -> None:
        super().__init__()
        self.choice = choice
        self.key = self.choice.label()
        self.draw("", self.key, "", self.key)

    def activate(self, window: QtToadApp) -> None:
        self.choose(window)

    def activate_in_switcher(self, switcher, window: QtToadApp) -> None:
        switcher.hide_switcher()
        self.activate(window)

    async def menu_entries_in(self, listing: Welcome) -> tuple[MenuEntry, ...]:
        return self.choice.held_actions(listing)


from toad.qt.page import Page  # re-export: callers already import Page from here
from toad.qt.metrics import UiGap, scaled_px


class BusAddress(BusAddressEntry, QLineEdit):
    """Where a reader types a machine to add by hand, under the welcome's Buses
    (`BusAddressEntry`, the field Textual's picker inherits too)."""

    def __init__(self, host: BusPickerHost) -> None:
        super().__init__(placeholderText=self.address_placeholder)
        self.returnPressed.connect(lambda: self.submit_address(host))

    def typed_address(self) -> str:
        return self.text()

    def clear_address(self) -> None:
        self.clear()


class HeldRowMenu(QObject):
    """A tree line's menu (SidebarItem.menu_entries), offered where a mouse right-clicks it
    or a finger is held on it (`FingerPress` delivers a held finger as the same context-menu
    request), in the window's own panel, as its menu is (QtToadApp.offer). Every tree of
    conversation rows has one, as every Textual sidebar row answers a right-click
    (`CommsRow.context_activation`). ``listing`` is what a row's entries act through: its
    ``host`` window, and for a bus row the listing that can forget it (`BusListing`)."""

    def __init__(self, rows: ConversationRows, listing) -> None:
        super().__init__(rows)
        self.rows, self.listing = rows, listing
        rows.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        rows.customContextMenuRequested.connect(self.offer)

    def offer(self, point: QPoint) -> None:
        """``point`` is in the tree's viewport, where QAbstractScrollArea reports it. The
        line's own menu (`SidebarItem.menu_entries_in`: a target line's declared
        `TargetLine.menu_entries`, a bus line's shared actions) is read, then offered."""
        rows = self.rows
        item: SidebarItem | None = rows.itemAt(point)
        if item is None:
            return
        # In the host window's coordinates, where `offer_entries` places its anchor
        # (`ConversationRows.window` names the app, hiding QWidget.window()).
        pressed = rows.viewport().mapTo(self.listing.host, point)
        asyncio.ensure_future(self.offer_read(item, QRect(pressed, QSize(1, 1))))

    async def offer_read(self, item: SidebarItem, anchor: QRect) -> None:
        """A target line's commands are read off the UI thread, then offered at the press."""
        entries = await item.menu_entries_in(self.listing)
        if entries:
            self.listing.host.offer_entries(entries, anchor)


@dataclass(frozen=True)
class QtTabAt(TabElement):
    """The open tab a Qt pointer is on (a QTabBar keeps no object per tab), as Textual's
    `SessionLabel`: its menu is the declared `TabElement.menu_entries`."""

    app: QtToadApp
    mode_name: str


class QtWelcomeOrigin(HomeSessionOrigin, HomeNavigation):
    """Standalone origin for Qt's welcome tab: Qt's `Welcome` widget cannot inherit
    `ProjectSessionOrigin` itself because `SessionOrigin`'s `AbstractHooksMeta` clashes
    with QWidget's shiboken6 metaclass, so the origin is a sibling object the window
    hands to `thread_navigation.open` through `QtWorkspaceViews.origin(WELCOME)`.

    Textual's `WelcomeScreen` (`screens/welcome.py:234`) inherits `HomeSessionOrigin`
    directly because its widget metaclass does not clash."""

    is_attached: bool = True

    def __init__(self, app: QtToadApp) -> None:
        self.app = app
        self.project_path = app.project_dir

    @property
    def coordination_root(self):
        return self.app.coordination_access.observation.observed().root


class Welcome(Page, NoConversationView, QWidget):
    """The home page: what the pages show while no tab is (the welcome mode, the origin new
    targets open from), and in place of a saved tab this app has not opened. It draws
    nothing: while it is selected the comms sidebar holds the whole window
    (`SidebarLayout.holds_alone`), with the banner, the bus, the buses and the hints the
    welcome page used to show."""

    mode = WELCOME

    def __init__(self, window: QtToadApp) -> None:
        super().__init__()
        self.host = window

    def workspace_navigation_owner(self, views):
        """Home navigates through the welcome's origin, as Textual's `WelcomeScreen` does."""
        return views.home_origin

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        """The home page leaves the sidebar as the user left it, as Textual's does."""


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

    def mount_rows(self, rows: Iterable[QTreeWidgetItem]) -> None:
        """Register the selected native children, then publish each line's placement."""
        rows = tuple(rows)
        self.parent.addChildren(rows)
        for row in rows:
            row.placed()

    def reconcile_keys(self, wanted: Iterable[KeyT], *, changed: frozenset[KeyT] = frozenset()) -> None:
        tree = self.parent.treeWidget()
        if tree is None:
            super().reconcile_keys(wanted, changed=changed)
            return
        with tree.batching_row_tones():
            super().reconcile_keys(wanted, changed=changed)

    def order_rows(self, position) -> None:
        """Move only the lines out of place, each where it belongs, reopening its groups."""
        tree = self.parent.treeWidget()
        if tree is None:
            self._order_rows_immediate(position)
            return
        with tree.batching_row_tones():
            self._order_rows_immediate(position)

    def _order_rows_immediate(self, position) -> None:
        ordered = sorted(self.member_order(), key=position)
        out_of_place = sum(1 for index, row in enumerate(ordered) if self.parent.child(index) is not row)
        if not out_of_place:
            return
        tree = self.parent.treeWidget()
        # When more than one child moves and none carries a Qt itemWidget (e.g. a channel's
        # thread rows), replace children in one bulk takeChildren/addChildren pair (2 signals)
        # instead of N individual takeChild/insertChild pairs (2N signals that each clear the
        # delegate cache and trigger O(N^2) sizeHint/StyledTextRenderer.prepare storms).
        if out_of_place > 1 and (tree is None or not any(tree.itemWidget(row, 0) is not None for row in ordered)):
            states = [(group, group.isExpanded(), group.isSelected()) for row in ordered for group in row.subtree()]
            self.parent.takeChildren()
            self.parent.addChildren(ordered)
            for group, opened, selected in states:
                group.setExpanded(opened)
                group.setSelected(selected)
            return
        for index, row in enumerate(ordered):
            if self.parent.child(index) is not row:
                states = [(group, group.isExpanded(), group.isSelected()) for group in row.subtree()]
                self.parent.takeChild(self.parent.indexOfChild(row))
                self.parent.insertChild(index, row)
                for group, opened, selected in states:
                    group.setExpanded(opened)
                    group.setSelected(selected)

    def retire_row(self, row: QTreeWidgetItem) -> None:
        for line in row.subtree():
            line.retired()
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
            kept.take(line)
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


class ConversationRows(LineMenuTree, RowTree, QTreeWidget):
    """A tree of Toad's conversation rows in the theme's sidebar tones, every other row a
    step off: pyqt-reactive's preview delegate paints each row's unread badge and label with
    its summary under it in muted text; a tap activates the line."""

    def __init__(self, window: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.window = window
        self.setHeaderHidden(True)
        cell = self.fontMetrics().averageCharWidth()
        # Members indent as Textual's `SidebarMembers` do (`RowTree.member_indent` cells).
        self.setIndentation(self.member_indent * cell)
        # One column: a line's text spans the row, as Textual's rows do. A channel line's
        # order control lies over the right end of its first line (`HeaderLineControl`).
        self.setColumnCount(1)
        window.renderer.themed(self, self.paint_colours)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Row backgrounds come polymorphically from each item's shared `row_tones`
        # (`ChannelRowFace.row_tones` for channels, `ThreadRowFace.row_tones` for threads)
        # prepared onto `BackgroundRole` when rows or themes change so Qt C++ paints them
        # with zero per-frame Python work.
        self.setAlternatingRowColors(False)
        self.setExpandsOnDoubleClick(False)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        # Tap activates (`itemClicked`) and long-press opens `HeldRowMenu`; nothing reads
        # Qt's selection model, and default `SingleSelection` left tapped/dragged channel
        # and thread rows stuck highlighted green until another row was tapped.
        self.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tone_batch_depth = 0
        self._dirty_tone_parents: dict[int, tuple[QTreeWidgetItem, int]] = {}
        self.itemClicked.connect(self.activate)
        self.itemExpanded.connect(self._fit_expanded_children)
        self.model().rowsInserted.connect(self._paint_row_tones_from)
        self.model().rowsRemoved.connect(self._paint_row_tones_from)

    def row_menu_context(self, line: ConversationRow):
        """Textual's context for the same line (`NavigationTarget.menu_context`): the open tab
        showing its target, and the channel it is listed under."""
        sidebar = self.window.sidebar
        return line.target.menu_context(sidebar, mode_name=sidebar.find_open_views().get(line.target_name),
                                        channel=line.listed_channel())

    @property
    def host(self) -> QtToadApp:
        """The window a row's menu entries act in (`HeldRowMenu`)."""
        return self.window

    def copy_name(self, name: str) -> None:
        self.window.copy_to_clipboard(name)

    def paint_colours(self) -> None:
        """The tree's stylesheet, prepared row-tone brushes, and line delegate colours under
        the current scheme. Omitting a base `QTreeWidget::item` background rule lets Qt's
        C++ style paint each item's `BackgroundRole` brush directly with zero per-frame
        Python calls."""
        window = self.window
        scheme = window.theme.color_scheme
        renderer = window.renderer
        bar = self.scrollbar_cells * self.fontMetrics().averageCharWidth()
        sidebar_bg = renderer.theme(SidebarToneColour)
        ink_hex = renderer.theme(WorkspaceTabTones.active_text_colour)
        hover_bg = scheme.to_hex(scheme.hover_bg)
        selection_bg = scheme.to_hex(scheme.selection_bg)
        selection_ink = scheme.to_hex(scheme.selection_text)
        QtLineRenderer.apply_sheet(
            self,
            f"QTreeWidget {{ background-color: {sidebar_bg}; color: {ink_hex};"
            f" border: none; border-radius: 3px; selection-background-color: {selection_bg}; }}"
            f"QTreeWidget::item:hover {{ background-color: {hover_bg}; }}"
            f"QTreeWidget::item:selected {{ background-color: {selection_bg}; color: {selection_ink}; }}"
            + _scrollbar_qss(renderer, fixed_thickness=False)
            + f"QScrollBar:vertical {{ width: {bar}px; }}"
            f"QScrollBar:horizontal {{ height: {bar}px; }}",
        )
        self._tone_brushes: dict[type[ThemeColour], QBrush] = {}
        self._paint_subtree_row_tones(self.invisibleRootItem())
        previous = self.itemDelegateForColumn(0)
        self.delegate = QtNameWaveDelegate(
            QColor(renderer.theme(WorkspaceTabTones.underline_colour)),
            scheme.to_qcolor(scheme.text_primary),
            scheme.to_qcolor(scheme.text_secondary),
            scheme.to_qcolor(scheme.selection_text),
            self,
        )
        self.setItemDelegateForColumn(0, self.delegate)
        if previous is not None:
            previous.deleteLater()

    def _row_tone_brush(self, tone: type[ThemeColour]) -> QBrush:
        brush = self._tone_brushes.get(tone)
        if brush is None:
            brush = self._tone_brushes[tone] = QBrush(QColor(self.window.renderer.theme(tone)))
        return brush

    @contextmanager
    def batching_row_tones(self) -> Iterator[None]:
        """Coalesce per-insert/remove row-tone repaints across a bulk tree update or reorder
        so painting N rows costs O(N) instead of O(N^2) and skips unchanged brushes."""
        self._tone_batch_depth += 1
        try:
            yield
        finally:
            self._tone_batch_depth -= 1
            if self._tone_batch_depth == 0 and self._dirty_tone_parents:
                dirty = tuple(self._dirty_tone_parents.values())
                self._dirty_tone_parents.clear()
                for parent, start in dirty:
                    if shiboken6.isValid(parent) and parent.treeWidget() is self:
                        self._paint_children_tones(parent, start)

    def _paint_children_tones(self, parent: QTreeWidgetItem, start: int = 0) -> None:
        for row in range(start, parent.childCount()):
            child = parent.child(row)
            brush = self._row_tone_brush(child.row_tones[row % 2])
            if child._painted_tone is not brush:
                child._painted_tone = brush
                child._painted_rgba = brush.color().rgba()
                child.setBackground(0, brush)

    def _paint_subtree_row_tones(self, parent: QTreeWidgetItem) -> None:
        self._paint_children_tones(parent)
        for row in range(parent.childCount()):
            child = parent.child(row)
            if child.childCount():
                self._paint_subtree_row_tones(child)

    def _paint_row_tones_from(self, parent_index, first: int, _last: int) -> None:
        parent = self.itemFromIndex(parent_index) if parent_index.isValid() else self.invisibleRootItem()
        if parent is None:
            return
        if self._tone_batch_depth > 0:
            key = id(parent)
            prev = self._dirty_tone_parents.get(key)
            if prev is None or first < prev[1]:
                self._dirty_tone_parents[key] = (parent, first)
            return
        self._paint_children_tones(parent, first)

    def drawBranches(self, painter: QPainter, rect: QRect, index) -> None:  # type: ignore[override]
        """Paint the left disclosure gutter in the item's prepared shared row tone."""
        brush = index.data(Qt.ItemDataRole.BackgroundRole)
        if brush is not None:
            painter.fillRect(rect, brush)
        super().drawBranches(painter, rect, index)

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

    _cached_char_width: tuple[QFont, int] | None = None

    def char_width(self) -> int:
        font = self.font()
        cached = self._cached_char_width
        if cached is not None and cached[0] == font:
            return cached[1]
        width = max(1, self.fontMetrics().averageCharWidth())
        self._cached_char_width = (QFont(font), width)
        return width

    def _fit_expanded_children(self, item: SidebarItem) -> None:
        """Fit children revealed when a collapsed group expands (skipped during resize)."""
        for index in range(item.childCount()):
            for line in item.child(index).visible_subtree():
                line.fit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """A new width fits every currently visible line's text again; collapsed groups fit
        lazily on expansion."""
        super().resizeEvent(event)
        if event.size().width() == event.oldSize().width():
            return
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            for line in root.child(index).visible_subtree():
                line.fit()

    def items(self):
        return (self.topLevelItem(index) for index in range(self.topLevelItemCount()))

    def retire_all(self) -> None:
        """Every line stops what it runs before the tree is destroyed with its window: a line
        that waves holds its place on the animation clock, which asks each one whether it is
        visible, and a line deleted with its wave running answered "the C++ object is deleted"
        into the clock on the way out."""
        for item in self.items():
            for line in item.subtree():
                line.retired()

    def redraw(self, draw: Callable[[KeptLines], object]) -> None:
        """Draw every line again in place, by kind and key: a line still wanted keeps its
        item, so a finger on it still lands and a group keeps its open or closed state; a
        line no longer wanted goes. Rows change in place; nothing is cleared and rebuilt."""
        with self.batching_row_tones():
            with KeptLines(self.invisibleRootItem()) as top:
                draw(top)


class NoopNavigation(NavigationRefresh):
    """Qt does not yet maintain a shared navigation cursor across the sidebar tree."""

    def apply(self) -> None:
        return


class HeaderLineControl(HeaderLine, QWidget):
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
        # The badge follows the title one cell after it (`HeaderLine.badge_stretch`); one
        # gap separates them from the order.
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
        self.badge.setText(self.badge_stretch(badge))
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
        self.channel: ChannelRowModel = UnpaintedChannel(name)
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

    @property
    def unread_counts(self):
        return self.sidebar.window.settings.sidebar.unread_counts

    def sync_members(self, changed: frozenset[str]) -> None:
        """Reconcile this channel's thread rows against the model through the shared
        `KeyedRows.reconcile_keys`, as Textual's ChannelGroup does."""
        if self.sidebar.model_state.shows_model():
            self.reconcile_keys(self.member_keys, changed=changed)

    def accepts_members(self) -> bool:
        return self.sidebar.model_state.shows_model()

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


class RowFittedTree(FittedRowTree):
    """A `ConversationRows` tree sized to its visible rows, up to `most_rows` before scrolling."""

    _last_fit_key: tuple | None = None

    def bind_row_fitting(self) -> None:
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.itemExpanded.connect(self._on_tree_expansion_changed)
        self.itemCollapsed.connect(self._on_tree_expansion_changed)

    def _on_tree_expansion_changed(self, _item) -> None:
        self._last_fit_key = None
        self.fit_rows()

    def _fit_key(self) -> tuple:
        count = self.topLevelItemCount()
        return (
            self.width(),
            count,
            tuple(
                (item.isExpanded(), item.childCount())
                for index in range(count)
                if (item := self.topLevelItem(index)) is not None
            ),
        )

    def fit_rows(self) -> None:
        """As tall as its shown lines, up to `most_rows` of them. Skips `doItemsLayout()`
        when width, item count and expansion state are unchanged — `ChannelActivitySidebar`
        fires on every bus observation, and unconditional `doItemsLayout()` was 4.7% of
        Pixel 8a's UI thread while scrolling."""
        key = self._fit_key()
        if key == self._last_fit_key and self.height() > 0:
            return
        self._last_fit_key = key
        self.doItemsLayout()
        heights, item = [], self.topLevelItem(0)
        while item is not None and len(heights) <= self.most_rows:
            heights.append(self.visualItemRect(item).height())
            item = self.itemBelow(item)
        target_height = sum(heights) + 2 * self.frameWidth()
        if self.height() != target_height:
            self.setFixedHeight(target_height)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._last_fit_key = None

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.fit_rows()


class QtSidebarBuses(BusListing, RowFittedTree, ConversationRows):
    """The buses this machine can open, under the bus line while the comms sidebar holds the
    window, as Textual's `SidebarBuses`: the rows the welcome page listed, in the first screen
    (above the search and the comms tree, which can list every thread). Its own tree, sized
    to its rows, so a long list of threads never pushes it out of sight. A Qt client is
    always remote, so this machine's own bus is not listed; a held finger on a saved one
    offers to forget it (`BusRow.held_actions`)."""

    most_rows = 6
    """Rows shown before the list scrolls: a tailnet's buses, without taking the screen."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self.held_menu = HeldRowMenu(self, self)
        self.bind_row_fitting()
        self.relist()

    def picker_host(self) -> BusPickerHost:
        return self.window

    def say_failure(self, reason: str) -> None:
        self.window.show_warning(reason, "Tailnet buses")

    def show_rows(self, rows: tuple[PickerRow, ...]) -> None:
        def draw(top: KeptLines) -> None:
            with top.group(OpenSection(self.buses_title)) as section:
                for choice in rows:
                    section.keep(BusRow(choice))
        self.redraw(draw)
        self.fit_rows()


class ChannelTreeSidebar(FindsOpenViews, QtWorkspaceHosted, SidebarStateMachine, ConversationRows):
    """A channel-tree view over the shared sidebar model: channels as expandable `ChannelLine`
    groups with `HeaderLineControl` + sort controls, members as `ThreadLine`s with live waving
    names and `HeldRowMenu`, reconciled incrementally through `SidebarStateMachine` and
    `QtChannelGroup`. `Sidebar` renders all channels; `ChannelActivitySidebar` reuses this
    exact widget scoped to the currently selected channel."""

    navigation: NavigationRefresh = NoopNavigation()
    groups: dict[str, QtChannelGroup]
    open_views: dict[str, str]

    def __init__(self, window: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(window, parent)
        self.groups = {}
        self.open_views = {}
        self.held_menu = HeldRowMenu(self, self)

    @property
    def app(self) -> QtToadApp:
        """The application, as a Textual sidebar's `app` names it for the shared readers
        (`FindsOpenViews`, `NavigationTarget.menu_context`)."""
        return self.window

    def accepts_observation(self) -> bool:
        """The tree follows every observation while it exists; placement or visibility hides it."""
        return True

    def coordination_access(self):
        return self.window.coordination_access

    def show_status(self, text: str) -> None:
        """Subclasses that display an observation status row override this."""

    def hide_status(self) -> None:
        """Subclasses that display an observation status row override this."""

    def present(self, **changes: object) -> None:
        """Run the shared state transition, whose model change reaches `sync`. A bare present
        (each observation, a show) draws no rows: rows change only through the change the state
        machine hands `sync`, as Textual's sidebar draws them. Redrawing every channel and
        thread here on each observation was 17% of the phone's UI thread during a burst of
        arrivals (2026-11-18)."""
        super().present(**changes)
        model = self.model_state.shown if self.model_state.shows_model() else self.model_state.retained_model()
        if model is None and self.groups:
            self.groups = {}
            self.redraw(lambda top: None)
        self.after_present(model)

    def after_present(self, model: SidebarModel | None) -> None:
        """Hook after `present` finishes."""

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Apply the change the shared state machine handed over. A partial one that keeps
        the channels' order touches only its header and member rows (`apply_comms`); every
        other one (all rows, a channel added, removed or moved) draws the tree again in
        place, keeping each still-wanted line's item."""
        if not self.model_state.shows_model():
            return
        model = self.model_state.shown

        def full_redraw() -> None:
            def draw(top: KeptLines) -> None:
                self.draw_leading_rows(top)
                self.draw_lines(model, top)
            self.redraw(draw)
            # The redraw rebuilt the channel items; the groups bind to the new ones so the next
            # partial change operates on live children.
            self._rebind_groups_from_tree(model)

        change.sync_sidebar(self, model.channels.rows, reorder=reorder, full_redraw=full_redraw)
        self.after_sync()

    def after_sync(self) -> None:
        """Hook after `sync` applies a change."""

    def model_replaced(self) -> None:
        """Clear rows before the new observation's redraw lands; the next `present` will
        repaint the new model's rows."""
        self.groups = {}
        self.redraw(lambda top: None)

    def reconcile_members(self):
        """Textual holds a DOM-level sync boundary here; Qt touches items directly."""
        return nullcontext()

    def draw_leading_rows(self, top: KeptLines) -> None:
        """Rows drawn before the channel groups (status and New Session in the all-channels sidebar)."""

    def channel_line(self, name: str, channel: ChannelRowModel, counts) -> ChannelLine:
        return ChannelLine.of(name, channel, counts=counts)

    def channels_to_draw(self, model: SidebarModel) -> Iterator[tuple[str, ChannelRowModel, Iterable[str]]]:
        raise NotImplementedError

    def draw_lines(self, model: SidebarModel, top: KeptLines) -> None:
        threads = model.threads.rows
        pending = self.window.thread_actions.pending
        counts = self.window.settings.sidebar.unread_counts
        for name, channel, members_shown in self.channels_to_draw(model):
            pinned_members = channel.pinned_members
            with top.group(self.channel_line(name, channel, counts)) as group:
                for member in members_shown:
                    group.keep(ThreadLine.of(member, threads[member], pinned=member in pinned_members,
                                             action_status=pending.get(member), counts=counts))

    def _rebind_groups_from_tree(self, model: SidebarModel) -> None:
        """Index the groups against the tree a wholesale redraw left. The redraw keeps a
        wanted line's item (`redraw`), so a channel whose row is still the one its group holds
        keeps that group and its header control, repainted from the row as drawn now; only a
        channel whose row is new builds a group. Building one makes its header's widgets, and
        on a phone a redraw arrives with each bus change, so rebuilding them all every time
        stalled the window for each change."""
        channel_models = model.channels.rows
        root = self.invisibleRootItem()
        previous = self.groups
        rebuilt: dict[str, QtChannelGroup] = {}
        for index in range(root.childCount()):
            root.child(index).rebind_group_into(self, channel_models, previous, rebuilt)
        self.groups = rebuilt


class Sidebar(ChannelTreeSidebar):
    """The all-channels sidebar: every channel (filtered by search), each opening to its
    threads, with the observation status row and New Session entry at the top."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__(window)
        self._status_text: str | None = None
        # The shared owner of the sidebar's search text and row-match decision. The
        # QLineEdit hosted by `QtSidebarSearch` writes the user's text into this
        # instance; `channels_to_draw` asks the filter's `matches(name)` when deciding
        # whether a row joins the tree. Textual's `SideBar` also owns one.
        self.filter: SidebarFilter = SidebarFilter()
        self.filter.subscribe(self._on_filter_changed)

    def _on_filter_changed(self, _value: str) -> None:
        """Every row may newly match or stop matching: all rows, as Textual's search
        follower re-syncs every group."""
        self.present(change=AllSidebarRows(), reorder=True)

    def show_status(self, text: str) -> None:
        """Record the status; `after_present` paints it in place."""
        self._status_text = text

    def hide_status(self) -> None:
        self._status_text = None

    def model_replaced(self) -> None:
        self._status_text = None
        super().model_replaced()

    def after_present(self, model: SidebarModel | None) -> None:
        self._refresh_status_only()
        if model is None:
            return
        self.window.channel_sort.update_order(model.observation.channel_order())
        self.window.paint_tabs()

    def draw_leading_rows(self, top: KeptLines) -> None:
        if self._status_text is not None:
            top.keep(StatusSection(self._status_text))
        top.keep(NewSessionRow())

    def channels_to_draw(self, model: SidebarModel) -> Iterator[tuple[str, ChannelRowModel, Iterable[str]]]:
        matches = self.filter.matches
        matching = self.filter.matching
        for name, channel in model.channels.rows.items():
            # A channel stays visible if its name matches OR any of its member thread
            # names do; hiding a channel whose only match is a buried thread would also
            # hide the thread. The group opens whichever path kept it.
            members_shown = matching(channel.members)
            if not matches(name) and not members_shown:
                continue
            yield name, channel, members_shown

    def _refresh_status_only(self) -> None:
        """Update just the status row at the top of the tree in place, without touching
        the channel subtrees that a targeted sync just redrew."""
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            if root.child(index).update_status_in(root, self._status_text):
                return
        if self._status_text is not None:
            target = StatusSection(self._status_text)
            root.insertChild(0, target)
            target.placed()


class ChannelActivitySidebar(RowFittedTree, ChannelTreeSidebar):
    """The active bar under a channel's composer: reuses the exact same `ChannelTreeSidebar`
    widget abstraction as the All channels bar, scoped to only the currently selected
    channel's tree (its header with unread badge & sort control, expanding to live member
    `ThreadLine`s with waving names, tap-to-open, and right-click/long-press menus)."""

    def __init__(self, window: QtToadApp, conversation: ConversationKind,
                 parent: QWidget | None = None) -> None:
        super().__init__(window, parent)
        self.channel_name = conversation.target.name
        self.bind_row_fitting()
        access = window.coordination_access
        access.sidebar_views.add(self)
        access.observation.observed().show_sidebar(self)

    def channel_line(self, name: str, channel: ChannelRowModel, counts) -> ChannelLine:
        return SelectedChannelLine.of(name, channel, counts=counts)

    def channels_to_draw(self, model: SidebarModel) -> Iterator[tuple[str, ChannelRowModel, Iterable[str]]]:
        channel = model.channels.rows.get(self.channel_name)
        if channel is not None:
            yield self.channel_name, channel, channel.members

    def fit_rows(self) -> None:
        super().fit_rows()
        if self.parentWidget() is not None:
            self.setVisible(self.topLevelItemCount() > 0)

    def after_sync(self) -> None:
        self.fit_rows()

    def after_present(self, model: SidebarModel | None) -> None:
        self.fit_rows()

    def close_activity(self) -> None:
        self.stop_showing()
        self.retire_all()



class QtSessionEntry(SessionEntries):
    """The Qt window's entry family."""


class QtHistorySessionEntry(QtSessionEntry, HistorySessionEntry, shows=(CommsTab,)):
    """The shared conversation entry, drawn in this window's ConversationView."""

    def __call__(self, sessions: SessionNavigator) -> ConversationView:
        return ConversationView(sessions.app, self)


class BusLabel(WelcomeLocation, ElidedLine):
    """Where the bus this window reads lives, as its connection names it, prefixed with
    the agent binding's `welcome_prefix` so the line reads the same way Textual's does
    at `screens/welcome.py:256` — `f"{agent_binding.welcome_prefix}{location}"`. A Qt
    client's own launch directory (on the phone, /data/data/…/app) says nothing about the
    Core it shows; the connection's location does.

    `welcome_prefix` is empty for `NoAgent` so a connection without an attached agent
    reads as before. With `AgentAttached`, the line reads e.g. `claude · <location>`."""

    def __init__(self, window: QtToadApp) -> None:
        super().__init__("")
        self.present(window)

    def present(self, app) -> None:
        """Name the connection observed now: a bus switch replaces the connection under the
        same window, so the line is read again whenever the observation answers."""
        line = self.location_line(app)
        self.setText(line)
        self.setToolTip(line)

    def location(self, app) -> str:
        return app.coordination_access.connection.location


class ConversationView(WireView, QtConversation, ConversationViewNavigation, SessionScope,
                       NavigationOwner, metaclass=PyQtWidgetMeta):
    """One conversation tab, Textual's `CommsChatView`: a `QtConversation` whose history is
    the conversation's wire, paged lazily by the pager Textual's channels use and drawn as
    virtual rows, read again whenever Core's stores change; the composer and activity its
    kind chooses, sending through the shared submissions to where its page source says.
    Inherits `MenuConversation` and its block menu from `QtConversation`."""

    # Until the live WireSource is wired in __init__, as `CommsChatView` declares it: the
    # wire is this view's queue, not its operational sources.
    queue_source: QueueSource = NoQueueSource()

    def __init__(self, app: QtToadApp, entry: QtHistorySessionEntry) -> None:
        super().__init__()
        self.app, self.entry = app, entry
        self.content_ready = asyncio.Event()
        label = entry.unobserved_tab().label()
        self._setup_conversation(app)
        self.message_history = QtWireHistory(self.messages, self, app)
        # WireSource IS a BusQueueSource (client/history.py): the submissions read its
        # pending/queued/held state as `CommsChatView` does. Resolve live CoreAccess via
        # `app.coordination_access` instead of `app.source().core` so opening or restoring
        # a tab during a disconnect never crashes `__init__` and reconnects seamlessly.
        wire = WireSource(
            Path(entry.key.root), self.conversation, entry.project, entry.viewer,
            self.configuration_state.fields.ui.message_style(),
            access=app.coordination_access, fragments=QtWireFragment)
        self.queue_source = wire
        self.message_history.initialize_source(wire)
        self.message_history.observe_source()
        # Textual's `CommsChatView.compose`: the flash under the window, the sweep painting
        # `working()` (an idle turn, the peer's observed row, or the first page loading),
        # the prompt (its info bar carries the thread status), then who is here.
        self.activity = tuple(self.conversation.compose_activity(self))
        # The inline consent prompt ("did you mean it?", edit/clear confirmations) — hidden
        # until the conversation asks, mounted below the composer so the picks sit where
        # the next message would be typed, mirroring Textual's Prompt.ask.
        self.question = QtQuestion(self.app, self)
        self.interactive_dialog = QtInteractiveDialog(self.app, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.messages, 1)
        layout.addWidget(self.feedback)
        layout.addWidget(self.agent_activity)
        # Current channel tree / peer activity sits right above the input box, matching ThreadView.
        for line in self.activity:
            layout.addWidget(line)
        self._composer_label = label
        self.reserve_composer(layout, lambda: self.conversation.prompt(self),
                              self._composer_mounted, kind=self.conversation.composer_kind(self))
        layout.addWidget(self.question)
        layout.addWidget(self.interactive_dialog)

    def _composer_mounted(self, composer: Composer) -> None:
        composer.labelled(self._composer_label)
        self.sync_status()

    @property
    def mode(self) -> str:
        return self.entry.mode

    def shown(self, window: QtToadApp, visited: Callable[[CommsTab], object]) -> None:
        visited(self.entry.identity)
        self.attach_pooled_composer_if_warm()
        self.reload()

    def wire_view_open(self) -> bool:
        """Whether this tab is still open in the workspace."""
        return self.app.workspace_sessions.views.get(self.mode) is self

    async def wait_content_ready(self) -> None:
        await self.content_ready.wait()

    async def retire_presentation(self) -> None:
        """The history lets go of its page reader; its rows go with the widgets."""
        self.message_history.close()

    @property
    def conversation(self) -> ConversationKind:
        return self.entry.key.conversation

    def reload(self) -> None:
        self.message_history.page_source.schedule_refresh(self)

    def stores_observed(self, revision) -> None:
        if self.needs_wire_refresh(revision):
            self.reload()

    def source_read(self) -> None:
        self.content_ready.set()

    def source_drawn(self) -> None:
        """Refresh thread status and working mark after a source read lands."""
        self.refresh_thread_status()
        self.sync_working()

    def read_thread_config(self) -> None:
        self.deliver(self._refresh_thread_config)

    async def thread_label_read(self) -> None:
        # The label reads Core's thread references: off the GUI loop, as compose access is.
        # Read on the loop it held a tab's opening for 104 ms on the desktop (frame probe).
        # Resolve `app.source()` inside `run_thread` so a disconnected FailedObservation
        # raises inside the worker where `_refresh_thread_config` catches transient errors.
        references = await self.app.preparation.run_thread(lambda: self.app.source().references())
        label = self.conversation.label(references)
        self._composer_label = label
        self.on_composer("label", lambda composer: composer.labelled(label))

    # The kind's composer and activity (ConversationActivity)

    def channel_prompt(self, placeholder: str) -> ChannelComposer:
        return ChannelComposer(self, self.app.renderer, placeholder)

    def message_prompt(self) -> MessageComposer:
        return MessageComposer(self, self.app.renderer)

    def channel_prompt_kind(self) -> type[ChannelComposer]:
        return ChannelComposer

    def message_prompt_kind(self) -> type[MessageComposer]:
        return MessageComposer

    def compose_channel_activity(self) -> Iterator[ChannelActivitySidebar]:
        yield ChannelActivitySidebar(self.app, self.conversation, parent=self)

    def compose_peer_activity(self, peer: ThreadIncarnation) -> Iterator[QtGoalBar | PeerActivity]:
        # The peer's goal sits over its activity and the composer, as the TUI's goal bar
        # sits over its prompt.
        self.goal_bar = QtGoalBar(self.app, self.app.renderer, peer, root=self.coordination_root)
        yield self.goal_bar
        self.thread_activity = PeerActivity(self.app, self.app.renderer, peer, self.sync_working)
        yield self.thread_activity

    # Commands the composer offers after a /

    @property
    def coordination_root(self) -> str:
        """The root the tab was opened on, as Textual's `CommsScreen.coordination_root`."""
        return self.entry.key.root

    @property
    def thread_identity(self):
        """The viewer on this conversation's wire, as Textual's `CommsScreen` acts."""
        return self.entry.viewer_identity


class QtWorkspaceViews(WorkspaceViews):
    """The Qt window's open views, stacked so the selected one shows; the home page stands
    in for a mode with no view here: the welcome page, or a saved tab this app has not
    opened."""

    def __init__(self, app: QtToadApp) -> None:
        self.app = app
        self.home = Welcome(app)
        self.home_origin = QtWelcomeOrigin(app)
        self.pages = QStackedWidget(app)
        self.pages.addWidget(self.home)
        self.views: dict[str, ConversationView] = {}

    @property
    def selected(self) -> Page:
        return self.pages.currentWidget()

    def resident_origin(self, identity: str) -> SessionOrigin:
        return self.home_origin if identity == WELCOME else NoSessionOrigin(identity)

    def navigation_owner(self) -> NavigationOwner:
        """Derived from the selected page, as Textual's `WorkspaceSessions.navigation_owner`
        is from the selected view: a conversation tab navigates as itself, home as the
        welcome's origin."""
        return self.selected.workspace_navigation_owner(self)

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
        if (menu := QtMenu.of(self.app)) is not None and menu.isVisible():
            menu.hide()
        if not toad_platform.host.auto_focus_composer:
            self.app.clear_focus()
            QGuiApplication.inputMethod().hide()
        page = self.prepare(mode)
        self.pages.setCurrentWidget(page)
        page.shown(self.app, visited)
        if not toad_platform.host.auto_focus_composer:
            self.app.clear_focus()

    def external_transcript_changed(self) -> None:
        """Every open view reads its CLI items, shown or parked, as Textual's screens do: a
        parked view that waited would draw what it missed as one burst on return."""
        for view in tuple(self.views.values()):
            view.external_transcript_changed()

    async def finish(self, view: ConversationView) -> None:
        # Rescue any pooled composer back to the workspace before tearing the view down so
        # closing a tab never destroys the reusable composer widget.
        self.composer_pool.release(view, keep_draft=False)
        # As Textual's `Conversation` unmount: the view's agent leaves its surface and stops
        # before the widgets it draws into are deleted.
        await view.operational_binding.retire_surface(view)
        view.close_configuration()
        self.pages.removeWidget(view)
        view.deleteLater()

    def swap_page(self, old: SessionScope, new: SessionScope) -> None:
        """Replace `old` with `new` in the pages stack and the views dict,
        preserving the mode slot. Called by `QtToadApp.replace_opening_view`
        when the opening placeholder transitions into the real bound view
        (Qt analogue of Textual's MainScreen handling both phases on one
        instance). The caller is responsible for setting `new.id = old.id`
        before this runs.

        This is only the structural replacement.  The replacement is not a
        visible conversation yet: `ThreadNavigator.mount` still has to bind
        its sources and thread.  Its `_prepare_content` method publishes the
        first selected frame after those facts exist.
        """
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
            if not toad_platform.host.auto_focus_composer:
                self.app.clear_focus()
        old.deleteLater()


PRESENCE_TRANSITIONS: dict[Qt.ApplicationState, Callable[[ApplicationPresence, QtToadApp], ApplicationPresence]] = {
    Qt.ApplicationState.ApplicationSuspended: lambda presence, app: presence.suspend(app),
    Qt.ApplicationState.ApplicationHidden: lambda presence, app: presence.suspend(app),
    Qt.ApplicationState.ApplicationInactive: lambda presence, app: presence.deactivate(app),
    Qt.ApplicationState.ApplicationActive: lambda presence, app: presence.activate(app),
}


class QtToadApp(ClientApplication, LayoutFollower, CorePrewarm, QtWorkspaceFrame, QtCommsHost, ScreenWideWindow, QWidget, metaclass=PyQtWidgetMeta):
    """The shared client application on Qt, over the Core its connection selects: the threads,
    and a tab per open conversation; the bar under them is Toad's: the menu button, back
    and forward through the visit history, and the tabs."""

    session_entries = QtSessionEntry

    def __init__(self, connection: CoreConnection, project: Checkout,
                 preparation: PreparationRuntime, scheme: ColourScheme,
                 launch: AgentBinding = NoAgent(), opening: LaunchOpening = NoLaunchOpening()) -> None:
        super().__init__(project, preparation, scheme)
        # The launch's agent, as Textual's `-a`: New Session starts its session.
        # The conversation the launch named (`--open`), opened once the saved tabs are back.
        self.initialize_client(launch, connection, opening=opening)
        # Walk local Core declarations once up front when connected locally (shared with
        # Textual via CorePrewarm); a remote connection's prewarm() is a no-op.
        self._prewarm_core_modules()
        self.input_attention = QtWindowAttention(self)
        self.action_keys = ActionKeys(lambda: self.settings)
        # Until a conversation reads Core's display references, bodies link the project's files.
        self.renderer = QtLineRenderer(scheme, LinkContext(project.path.resolve(), ProjectReferences()),
                                       self.settings.diff)
        self.row_pictures = RowPictures(self.preparation.max_bytes)
        """The rows every open history has drawn, kept as pictures within the app's limit."""
        # The one animation clock every effect's frames come from (ui_theme's
        # `AnimationClock`, as Textual's colours own theirs), on one Qt timer.
        self._animation_timer = QTimer(self)
        # Motion ticks every frame the screen shows; a coarse timer's few percent of slack
        # would land some ticks between two frames and show one frame twice.
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.timeout.connect(self._tick_animation)
        self._animation_interval: float | None = None
        self._animations_paused = False
        self._layout_pending = False
        self._presence: ApplicationPresence = ACTIVE_PRESENCE
        self.animation_clock = QtAnimationClock(self._schedule_animation, enabled=animations_enabled())
        # Notices and the work the reader waits on float over the pages, never in their layout.
        self.float_layer = QtFloatLayer(
            self.theme.color_scheme, self.renderer, self.animation_clock, self)
        # One background task per transfer kind, cancelled + replaced when the same
        # kind is submitted again (Qt analog of Textual's run_worker exclusive=True).
        # Populated by `start_transfer_task`; the dict is the live registry.
        self._transfer_tasks: dict[type[Transfer], asyncio.Task[None]] = {}
        self.workspace_sessions = QtWorkspaceViews(self)
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
            QtSidebarPanels(self.sidebar_state, (QtPanelEntry.of(CHANNELS_PANEL, self.sidebar, (self.channel_sort,), CHANNELS_PANEL.title),)),
            parent=self)
        # While no tab is shown the comms sidebar holds the window (`SidebarLayout.holds_alone`)
        # and carries what the welcome page did: Toad's banner, the bus this window reads and
        # the buses it can open above the search and rows, so they are in the first screen
        # however many threads the rows list; the hints and the field to add a machine below
        # them. Beside a tab only the search and rows show. Textual's `ChannelsSidebar`
        # composes the same parts in the same order.
        self.banner = Banner(self.renderer.theme(PrimaryColour))
        self.renderer.follows_theme(self.banner, lambda: self.banner.paint_in(self.renderer.theme(PrimaryColour)))
        self.bus_label = BusLabel(self)
        self.bus_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.renderer.themed(self.bus_label, lambda: self.bus_label.setStyleSheet(self.renderer.color_style(MutedRole)))
        self.hints = QLabel(_strip_menu_markup_shared(self.welcome_hints))
        self.hints.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hints.setWordWrap(True)
        self.renderer.themed(self.hints, lambda: self.hints.setStyleSheet(self.renderer.color_style(MutedRole)))
        self.bus_address = BusAddress(self)
        self.sidebar_buses = QtSidebarBuses(self)
        self.channels_column = QWidget(self)
        column = QVBoxLayout(self.channels_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(UiGap.tight)
        for part in (self.banner, self.bus_label, self.sidebar_buses):
            column.addWidget(part)
        column.addWidget(self.sidebar_search, 1)
        # A clear gap under the rows: a row the tree's edge cuts must not read as running
        # under the hints.
        column.addSpacing(UiGap.loose)
        for part in (self.hints, self.bus_address):
            column.addWidget(part)
        self.sole_parts = (self.banner, self.bus_label, self.sidebar_buses, self.hints, self.bus_address)
        self.shown_alone: bool | None = None
        self.thread_pane = ThreadSettingsPane(self, parent=self,
                                              project_path=self.project_dir.path)
        # The pages and both sidebars live in one chrome that places them where the shared
        # SidebarChromeArrangement resolves them, as Textual's WorkspaceChrome does: a docked
        # sidebar pushes the pages, a floating one lies over them, a folded one is its strip.
        # Parent self throughout: a parentless QWidget on Qt-for-Android becomes its own
        # top-level window with its own EGL surface (PR #1885's SIGABRT).
        self.chrome = QtWorkspaceChrome(self.sidebar_layout, self.workspace_sessions.pages,
                                        clock=self.animation_clock,
                                        available=self._pane_available, parent=self)
        self.channels_side = QtSideBar(
            self.sidebar_layout, ChannelsSidebarPlacement, self.channels_column,
            heading=partial(self._pane_heading, ChannelsSidebarPlacement),
            laid_out=self.rearrange_sidebars, client=self, parent=self.chrome)
        self.thread_side = QtSideBar(
            self.sidebar_layout, ThreadSidebarPlacement, self.thread_pane,
            heading=partial(self._pane_heading, ThreadSidebarPlacement),
            laid_out=self.rearrange_sidebars, client=self, parent=self.chrome)
        self.chrome.sidebars = (self.channels_side, self.thread_side)
        # ≡ is in Android's Noto Sans Math; ☰ is in no font Android ships, so it drew a box.
        self.menu = self.bar_button("≡", "Menu", self.show_menu)
        self.back = self.bar_button("←", "Back", partial(self.tab_order.navigate, -1))
        self.forward = self.bar_button("→", "Forward", partial(self.tab_order.navigate, 1))
        # pyqt-reactive's tab bar in the theme's tab style; a dragged tab moves in the
        # shared tab order, which the bar then draws again.
        self.tabs = QtSessionTabBar(
            self.animation_clock,
            QColor(self.renderer.theme(WorkspaceTabTones.underline_colour)),
            QColor(self.renderer.theme(WorkspaceTabTones.active_text_colour)),
            QColor(self.renderer.theme(WorkspaceTabTones.inactive_text_colour)),
        )
        self.tabs.setTabsClosable(True)
        self.tabs.setExpanding(False)
        # Each tab keeps its own width and the strip scrolls: a swipe moves it on the phone
        # (every scroll area scrolls by finger, `finger_scrolling`), where many tabs were
        # squeezed behind two arrow buttons. A right-click, which a held finger is
        # (`finger_press`), offers the shared tab menu: moving and closing.
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.tabBarClicked.connect(self.visit_index)
        self.tabs.tabCloseRequested.connect(self.close_index)
        self.tabs.tabMoved.connect(self.move_index)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.offer_tab_menu)
        self.tab_strip = QScrollArea(self)
        self.tab_strip.setWidget(self.tabs)
        self.tab_strip.setWidgetResizable(True)
        self.tab_strip.setFrameShape(QFrame.Shape.NoFrame)
        self.tab_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tab_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tab_strip.setObjectName("toad-tab-strip")
        self.tab_scrollbar = QScrollBar(Qt.Orientation.Horizontal, self)
        self.tab_scrollbar.setObjectName("toad-tab-scrollbar")
        self.tab_scrollbar.hide()
        strip_hbar = self.tab_strip.horizontalScrollBar()
        strip_hbar.rangeChanged.connect(self._sync_tab_scrollbar_range)
        strip_hbar.valueChanged.connect(self.tab_scrollbar.setValue)
        self.tab_scrollbar.valueChanged.connect(strip_hbar.setValue)
        self.tab_column = QWidget(self)
        self.tab_column.setObjectName("toad-tab-column")
        tab_column_layout = QVBoxLayout(self.tab_column)
        tab_column_layout.setContentsMargins(0, 0, 0, 0)
        tab_column_layout.setSpacing(0)
        tab_column_layout.addWidget(self.tab_scrollbar)
        tab_column_layout.addWidget(self.tab_strip)
        self._last_tab_mode: str | None = None
        bar = QHBoxLayout()
        bar.setSpacing(UiGap.tight)
        bar.setContentsMargins(0, 0, 0, 0)
        self._nav_separators = tuple(self._nav_separator() for _ in range(3))
        bar.addWidget(self.menu)
        bar.addWidget(self._nav_separators[0])
        bar.addWidget(self.back)
        bar.addWidget(self._nav_separators[1])
        bar.addWidget(self.forward)
        bar.addWidget(self._nav_separators[2])
        bar.addWidget(self.tab_column, 1)
        # The bar row is Toad's header band: a frame in the theme's header tone. Notices
        # float over the pages in `float_layer`; they are no part of this band.
        self.navigation = chrome = QFrame(self)
        chrome.setObjectName("toad-navigation")
        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        # QtMenu is the window's one pop-up menu (the application menu, the held/right-click
        # row menus, the bus-connect choices, a sort choice). It floats over the content as
        # a child of the window, in no layout, so opening it moves nothing (`QtMenu`).
        self.menu_panel = QtMenu(self)
        self.renderer.themed(self.menu_panel, lambda: self.menu_panel.paint(self.renderer))
        # Bus switcher: inline overlay panel for the hamburger "Switch bus" entry.
        # Registered as a `BusListing` so `tailnet_answered` routes answers to it
        # while shown (same shape as Welcome, which is always registered).
        from toad.qt.bus_switcher import QtBusSwitcher
        # Welcome is always a BusListing; the switcher registers/deregisters
        # itself while shown so answers reach both.
        self._bus_listings: list[BusListing] = [self.sidebar_buses]
        self.bus_switcher = QtBusSwitcher(self)
        chrome_layout.addWidget(self.bus_switcher)
        # Paste surface for the bus-connect remediation ("Paste a profile" option on the
        # BusConnectDecision menu). Inline QFrame child of the window, not a QDialog —
        # same EGL rationale as QtMenu: a top-level popup needs its own surface and
        # deadlocks the compositor on Pixel 8a.
        self.profile_paste_panel = QtProfilePastePanel(self)
        chrome_layout.addWidget(self.profile_paste_panel)
        chrome_layout.addLayout(bar)
        self._rest_bottom_margin: int | None = None
        self._keyboard_open: bool = False
        self._base_app_font_pt: float = QApplication.font().pointSizeF()
        self._applied_font_scale: int = 100
        self.renderer.themed(self, self.paint_chrome_colours)
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        self.apply_layout_preferences()
        self.fit_screen()
        # The channels sidebar opens as the shared `sidebar.hide` setting says, as Textual's
        # ChannelsSidebar mounts; the thread sidebar starts folded, as Textual's ThreadSidebar.
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, self.settings.sidebar.hide)
        self.rearrange_sidebars()
        self.changes = self.coordination_access.events.subscribe(CoordinationObserved, self.stores_changed)
        # CLI drafts and finished items change no thread status, so `CoordinationObserved`
        # never carries them: without this a CLI's newest item waited for its next one.
        self.transcripts = self.coordination_access.events.subscribe(
            ExternalTranscriptChanged, self.external_transcript_changed)
        self.history = self.tab_order.events.subscribe(TabHistoryChanged, self.history_changed)
        self.history_changed()
        # Android Back via native C++ QShortcut (zero per-event Python filter overhead);
        # unhandled Escape bubbles from child widgets into QtToadApp.keyPressEvent.
        self._back_shortcut = QShortcut(QKeySequence("Back"), self)
        self._back_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._back_shortcut.activated.connect(self._handle_back_shortcut)
        self._zoom_shortcuts = (
            self.action_keys.bind(
                self, ZoomInAction(), lambda: self.adjust_message_font_scale(5),
                Qt.ShortcutContext.ApplicationShortcut,
            ),
            self.action_keys.bind(
                self, ZoomOutAction(), lambda: self.adjust_message_font_scale(-5),
                Qt.ShortcutContext.ApplicationShortcut,
            ),
            self.action_keys.bind(
                self, ResetZoomAction(), self.reset_message_font_scale,
                Qt.ShortcutContext.ApplicationShortcut,
            ),
        )
        self.winId()
        FingerPress.install(QApplication.instance()).watch(self.windowHandle())
        self.windowHandle().safeAreaMarginsChanged.connect(self.fit_safe_area)
        self._safe_area_resync_pending = False
        self._ime_watcher = self._watch_android_ime_inset()
        input_method = QGuiApplication.inputMethod()
        input_method.visibleChanged.connect(
            self._schedule_safe_area_resync, Qt.ConnectionType.QueuedConnection
        )
        input_method.keyboardRectangleChanged.connect(
            self._schedule_safe_area_resync, Qt.ConnectionType.QueuedConnection
        )
        self.fit_safe_area(self.windowHandle().safeAreaMargins())
        self._display_screens: set[QScreen] = set()
        self.windowHandle().screenChanged.connect(self.follow_display)
        self.follow_display()
        # The saved settings drawn now the widgets exist, as Textual's `on_load` applies them
        # all; from here each change applies its `Effect` (`ClientApplication.open_settings`).
        self.saved_settings.apply_all()
        self.input_attention.attach()

    def connection_for(self, choice: BusChoice) -> CoreConnection:
        """The connection a chosen bus names, read by the launch's connection capability so
        desktop Qt can switch Local -> Remote -> Local without losing `LocalCoreConnection`."""
        return self._launch_connection.chosen(list(choice.arguments(())))

    def _nav_separator(self) -> QFrame:
        """Thin 1 px vertical divider in the navigation bar, matching `QtSideBarToggle`'s splitter."""
        separator = QFrame(self)
        separator.setObjectName("toad-nav-separator")
        separator.setFixedWidth(1)
        separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        return separator

    def bar_button(self, text: str, tip: str, action) -> QtTextButton:
        button = QtTextButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setMinimumSize(36, 32)
        font = button.font()
        font.setPointSizeF(font.pointSizeF() * 1.2)
        button.setFont(font)
        button.clicked.connect(action)
        return button

    def capture_command_origin(self) -> WindowCommandOrigin:
        return WindowCommandOrigin(self)

    KEYBOARD_MARGIN_THRESHOLD: ClassVar[int] = 100
    """Logical-pixel jump above the resting bottom safe-area inset that marks an open soft
    keyboard (system gesture/3-button bars sit at 0-56 dp; touch keyboards are 250-350 dp)."""

    def _watch_android_ime_inset(self) -> QFileSystemWatcher | None:
        """Watch `TOAD_IME_INSET_FILE` so dismissing the Android keyboard via Back always
        resyncs safe-area margins even when Qt's `QtWindow` deduplicates an unchanged
        resting `safeAreaMarginsChanged` signal."""
        inset_path = os.environ.get("TOAD_IME_INSET_FILE")
        if not inset_path or not Path(inset_path).exists():
            return None
        watcher = QFileSystemWatcher([inset_path], self)
        watcher.fileChanged.connect(self._on_ime_inset_file_changed)
        return watcher

    def _on_ime_inset_file_changed(self, path: str) -> None:
        if self._ime_watcher is not None and path not in self._ime_watcher.files() and Path(path).exists():
            self._ime_watcher.addPath(path)
        self._schedule_safe_area_resync()

    def _schedule_safe_area_resync(self) -> None:
        """Defer safe-area resync off `QAndroidInputContext::runOnQtThread()`."""
        if not self._safe_area_resync_pending:
            self._safe_area_resync_pending = True
            QTimer.singleShot(0, self, self._resync_safe_area)

    def _resync_safe_area(self) -> None:
        self._safe_area_resync_pending = False
        handle = self.windowHandle()
        if handle is not None:
            self.fit_safe_area(handle.safeAreaMargins())

    def _android_ime_bottom_dp(self) -> int | None:
        """Authoritative IME bottom inset (in logical dp) written by `ToadActivity`, or None
        when not running under Android's inset handoff file.

        Qt-for-Android's `QtWindow.onLayoutChange` reads raw `getRootWindowInsets()` (which
        bypasses `ToadActivity`'s folded IME inset on `android.R.id.content`) and emits a
        stale resting bottom margin whenever `m_editText` repositions on a tap inside an
        already-focused composer; conversely, pressing Back to dismiss the keyboard can
        write `0` before `QtWindow.safeAreaMargins()` drops its cached folded IME height.
        Checking `TOAD_IME_INSET_FILE` keeps the bottom margin authoritative in both
        directions."""
        inset_path = os.environ.get("TOAD_IME_INSET_FILE")
        if not inset_path:
            return None
        try:
            raw = Path(inset_path).read_text(encoding="ascii").strip()
            ime_px = int(raw) if raw else 0
        except (OSError, ValueError):
            return None
        if ime_px <= 0:
            return 0
        dpr = max(1.0, self.devicePixelRatioF())
        return round(ime_px / dpr)

    def fit_safe_area(self, margins: QMargins) -> None:
        """Keep every row clear of the status bar, navigation bar and soft keyboard.

        On Android 15, ``ToadActivity`` folds ``WindowInsets.Type.ime().bottom`` into
        ``systemBars().bottom`` so ``safeAreaMarginsChanged`` carries the exact keyboard
        height without resizing the EGL ``SurfaceView``. While the keyboard is up, bottom-
        docked chrome (bottom navigation bar and collapsed bottom sidebar toggle strips)
        hides so the composer sits flush above the keyboard."""
        ime_bottom = self._android_ime_bottom_dp()
        if ime_bottom is not None:
            if ime_bottom > 0 and ime_bottom > margins.bottom():
                margins = QMargins(margins.left(), margins.top(), margins.right(), ime_bottom)
            elif (
                ime_bottom == 0
                and self._rest_bottom_margin is not None
                and margins.bottom() > self._rest_bottom_margin
            ):
                margins = QMargins(
                    margins.left(), margins.top(), margins.right(), self._rest_bottom_margin
                )
        self.setContentsMargins(margins)
        bottom = margins.bottom()
        if self._rest_bottom_margin is None or (
            (ime_bottom is None or ime_bottom == 0) and bottom < self._rest_bottom_margin
        ):
            self._rest_bottom_margin = bottom
        if ime_bottom is not None:
            self._keyboard_open = ime_bottom > 0
        else:
            self._keyboard_open = (bottom - self._rest_bottom_margin) >= self.KEYBOARD_MARGIN_THRESHOLD
        self._sync_keyboard_chrome()
        self._notify_viewport_geometry()

    def _notify_viewport_geometry(self) -> None:
        """Notify floating chrome and the active page when window size or safe-area margins
        change, instead of installing permanent per-event `eventFilter`s on `QtToadApp`."""
        if self.float_layer.isVisible():
            self.float_layer.place()
        self.workspace_sessions.selected.viewport_geometry_changed()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._notify_viewport_geometry()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.adjust_message_font_scale(5 if delta > 0 else -5)
            event.accept()
            return
        super().wheelEvent(event)

    def _sync_keyboard_chrome(self) -> None:
        hide_nav = (
            self._keyboard_open
            and self.settings.ui.navigation_bar.yields_to_keyboard
            and not self.bus_switcher.isVisible()
            and not self.profile_paste_panel.isVisible()
        )
        self.navigation.setVisible(not hide_nav)
        self.chrome.set_keyboard_open(self._keyboard_open)

    def stores_changed(self, event: CoordinationObserved, subscription: object) -> None:
        self.bus_label.present(self)
        self.workspace_sessions.selected.stores_observed(event.revision)

    def external_transcript_changed(self, event: ExternalTranscriptChanged, subscription: object) -> None:
        self.workspace_sessions.external_transcript_changed()

    def history_changed(self, *event: object) -> None:
        """Back and forward are live exactly when the visit history has a step that way."""
        self.back.setEnabled(self.tab_order.history_target(-1) is not None)
        self.forward.setEnabled(self.tab_order.history_target(1) is not None)

    def source(self) -> ObservedSource:
        observed = self.coordination_access.observation.observed()
        return ObservedSource(observed.core, observed.root, self.project_dir)

    # Tabs: SessionNavigation owns the open entries, TabOrder their order, the saved roster
    # and the visit history; the bar draws the shared tab projection.

    def _schedule_animation(self, interval: float | None) -> None:
        """The clock's one timer: tick every ``interval`` seconds, or stop."""
        self._animation_interval = interval
        if not shiboken6.isValid(self._animation_timer):
            return
        if interval is None or self._animations_paused:
            self._animation_timer.stop()
        else:
            self._animation_timer.start(max(1, round(interval * 1000)))

    def set_animations_paused(self, paused: bool) -> None:
        if self._animations_paused == paused:
            return
        self._animations_paused = paused
        self._schedule_animation(self._animation_interval)

    def _tick_animation(self) -> None:
        self.animation_clock.tick()

    def follow_display(self, *_changed) -> None:
        """The clock's frame interval is the screen's this window is on: it follows the window to
        another screen, and a screen that changes its refresh rate (a phone's adaptive 60/120 Hz)."""
        screen = self.windowHandle().screen()
        self.animation_clock.frame_interval = frame_interval(screen)
        if screen is not None and screen not in self._display_screens:
            self._display_screens.add(screen)
            screen.refreshRateChanged.connect(self.follow_display)

    def paint_tabs(self) -> None:
        """The tabs as the navigation has them: a tab's title, unread count and busy wave; the
        bar redraws only what changed (`show_tabs`). The selected tab is marked every time, as
        before: marking it presents the panes, and a pane state change that asks for nothing
        else (the sidebar leaving the whole window as the first tab opens) is presented there."""
        self.tabs.blockSignals(True)
        badge = self.settings.sidebar.unread_counts.badge
        tabs = tuple(self.session_navigation.tabs)
        self.tabs.show_tabs([(tab.label() + tab.unread_suffix(badge), tab.mode_name) for tab in tabs])
        self.tabs.follow_tabs(tabs)
        self.tabs.blockSignals(False)
        self.mark_current()

    def mark_current(self) -> None:
        modes = self.session_navigation.tab_modes
        mode = self.selected_mode
        selection_changed = mode != self._last_tab_mode
        self._last_tab_mode = mode
        self.tabs.setCurrentIndex(modes.index(mode) if mode in modes else -1)
        # Keep strip height and panes synced on every refresh, but only scroll the strip
        # to the selected tab when selection actually changed so user scrolling never snaps back.
        QTimer.singleShot(0, partial(self.show_current_tab, scroll_to_current=selection_changed))

    def _tab_scrollbar_height(self) -> int:
        cells = platform_input().tab_scrollbar_cells
        return cells * self.tabs.fontMetrics().lineSpacing() if cells else 0

    def _sync_tab_scrollbar_range(self, minimum: int, maximum: int) -> None:
        strip_hbar = self.tab_strip.horizontalScrollBar()
        self.tab_scrollbar.setRange(minimum, maximum)
        self.tab_scrollbar.setPageStep(strip_hbar.pageStep())
        self.tab_scrollbar.setSingleStep(strip_hbar.singleStep())
        self.tab_scrollbar.setValue(strip_hbar.value())
        bar_h = self._tab_scrollbar_height()
        if bar_h > 0 and maximum > minimum:
            self.tab_scrollbar.setFixedHeight(bar_h)
            self.tab_scrollbar.show()
        else:
            self.tab_scrollbar.hide()

    def show_current_tab(self, *, scroll_to_current: bool = True) -> None:
        self.tabs.sync_strip_width(self.tab_strip.viewport().width())
        self.tab_strip.setFixedHeight(self.tabs.sizeHint().height())
        strip_hbar = self.tab_strip.horizontalScrollBar()
        self._sync_tab_scrollbar_range(strip_hbar.minimum(), strip_hbar.maximum())
        scroller = QScroller.scroller(self.tab_strip.viewport())
        if scroll_to_current and scroller.state() == QScroller.State.Inactive and (index := self.tabs.currentIndex()) >= 0:
            rect = self.tabs.tabRect(index)
            self.tab_strip.ensureVisible(rect.center().x(), rect.center().y(), rect.width() // 2 + UiGap.dialog, 0)
        self.present_panes()
        self.input_attention.update()

    def paint_chrome_colours(self) -> None:
        """Delegate chrome theming to each widget's inherited colour declarations (`SidebarSurface`,
        `SidebarToggleFace`, `SidebarSearchField`, `SidebarPanelCollapse`, `WorkspaceTabTones`,
        `ScrollbarTones`) with zero parallel QSS colour copies."""
        scheme = self.theme.color_scheme
        renderer = self.renderer
        scale = self._applied_font_scale
        bar_bg = renderer.theme(WorkspaceTabTones.bar_tone)
        inactive_bg = renderer.theme(WorkspaceTabTones.inactive_tab_tone)
        selected_bg = renderer.theme(WorkspaceTabTones.selected_tab_tone)
        hover_bg = renderer.theme(WorkspaceTabTones.hover_tone)
        underline_hex = renderer.theme(WorkspaceTabTones.underline_colour)
        active_ink = renderer.theme(WorkspaceTabTones.active_text_colour)
        inactive_ink = renderer.theme(WorkspaceTabTones.inactive_text_colour)
        close_idle = renderer.theme(WorkspaceTabTones.close_idle_colour)
        close_hover = renderer.theme(WorkspaceTabTones.close_hover_colour)
        nav_hover_bg = renderer.theme(WorkspaceTabTones.header_button_hover_bg)
        nav_hover_fg = renderer.theme(WorkspaceTabTones.header_button_hover_fg)
        nav_disabled_fg = renderer.theme(WorkspaceTabTones.header_button_disabled_fg)
        scrollbar_qss = _scrollbar_qss(renderer, scale=scale)
        self.setStyleSheet(scrollbar_qss)
        for side in self.chrome.sidebars:
            side.paint_theme(renderer, scrollbar_qss=scrollbar_qss, scale=scale)
        self.sidebar_search.paint_theme(renderer, scale=scale)
        self.thread_pane.paint_theme(renderer, scale=scale)
        self.tab_scrollbar.setStyleSheet(
            _scrollbar_qss(renderer, selector="#toad-tab-scrollbar", scale=scale, fixed_thickness=False)
        )
        self.tab_column.setStyleSheet(f"#toad-tab-column {{ background-color: {bar_bg}; }}")
        self.tab_strip.setStyleSheet(
            f"#toad-tab-strip, #toad-tab-strip > QWidget {{"
            f" border: none; padding: 0px; background-color: {bar_bg}; }}"
        )
        tab_pad_y = scaled_px(4, scale)
        tab_pad_l = scaled_px(5, scale)
        tab_pad_r = scaled_px(1, scale)
        border_w = scaled_px(2, scale)
        tab_gap = self.tabs.scaled_tab_gap()
        self.tabs.setStyleSheet(
            f"QTabBar {{ background-color: {bar_bg}; color: {active_ink}; }}"
            f"QTabBar::tab {{ background-color: {inactive_bg}; color: {inactive_ink}; border: none;"
            f" border-bottom: {border_w}px solid {hover_bg};"
            f" padding: {tab_pad_y}px {tab_pad_r}px {tab_pad_y}px {tab_pad_l}px; margin-right: {tab_gap}px;"
            " border-top-left-radius: 0px; border-top-right-radius: 0px; }"
            f"QTabBar::tab:hover {{ background-color: {hover_bg}; color: {active_ink}; }}"
            f"QTabBar::tab:selected {{ background-color: {selected_bg}; color: {active_ink};"
            f" font-weight: bold; border-bottom: {border_w}px solid {underline_hex}; }}"
            f"QToolButton#tab-close-button {{"
            f" border: none; border-radius: 0px; padding: 0px;"
            f" background: transparent; color: {close_idle}; font-weight: bold; }}"
            f"QToolButton#tab-close-button:hover, QToolButton#tab-close-button:pressed {{"
            f" background: {hover_bg}; color: {close_hover}; }}"
        )
        self.tabs.set_colours(QColor(underline_hex), QColor(active_ink), QColor(inactive_ink))
        sep_hex = self.palette().color(QPalette.ColorRole.Mid).name()
        nav_edge = self.settings.ui.navigation_bar.qt_separator_edge
        nav_pad = scaled_px(2, scale)
        sep_margin = scaled_px(4, scale)
        self.navigation.setStyleSheet(
            f"QFrame#toad-navigation {{ background-color: {bar_bg}; padding: {nav_pad}px {nav_pad}px;"
            f" border: none; {nav_edge}: 1px solid {sep_hex}; }}"
            f"QFrame#toad-nav-separator {{ border: none; padding: 0px; margin: {sep_margin}px 0px; background: {sep_hex}; }}"
            f"QFrame#toad-navigation QToolButton {{"
            f" background: transparent; color: {active_ink}; border: none; border-radius: 0px; }}"
            f"QFrame#toad-navigation QToolButton:hover {{"
            f" background-color: {nav_hover_bg}; color: {nav_hover_fg}; }}"
            f"QFrame#toad-navigation QToolButton:disabled {{"
            f" color: {nav_disabled_fg}; }}"
        )
        self.float_layer.follow_scheme(scheme)

    def settings_widgets(self, widget_type: type) -> list:
        return capability_widgets(self, widget_type)

    def apply_text_scale(self, percent: int) -> None:
        """Single hoisted UI-scale owner: scales fonts, chrome buttons, tabs, sidebars,
        search boxes, scrollbars, and row geometry together like terminal zoom."""
        clamped = max(50, min(200, int(percent)))
        if clamped == self._applied_font_scale:
            return
        self._applied_font_scale = clamped
        base = self._base_app_font_pt if self._base_app_font_pt > 0 else 10.0
        font = QFont(QApplication.font())
        font.setPointSizeF(round(base * clamped / 100.0, 2))
        QApplication.setFont(font)
        btn_min_w = scaled_px(36, clamped)
        btn_min_h = scaled_px(32, clamped)
        for button in (self.menu, self.back, self.forward):
            btn_font = QFont(font)
            btn_font.setPointSizeF(round(font.pointSizeF() * 1.2, 2))
            button.setFont(btn_font)
            button.setMinimumSize(btn_min_w, btn_min_h)
        self.tabs.apply_scale(clamped)
        self.paint_chrome_colours()
        self.show_current_tab(scroll_to_current=False)
        self.rearrange_sidebars()
        self.sidebar.paint_colours()
        for index in range(self.sidebar.topLevelItemCount()):
            for item in self.sidebar.topLevelItem(index).subtree():
                item.fit()
        self.sidebar.doItemsLayout()

    def apply_layout_preferences(self) -> None:
        """The navigation bar sits above or below the conversation row as `ui.navigation_bar`
        places it, the setting Textual's `WorkspaceHeader` follows, and the unified text scale
        applies across the application."""
        layout = self.layout()
        for index, widget in enumerate(self.settings.ui.navigation_bar.around(self.navigation, self.chrome)):
            layout.removeWidget(widget)
            layout.insertWidget(index, widget, 1 if widget is self.chrome else 0)
        self.apply_text_scale(self.settings.ui.message_font_scale)
        self.paint_chrome_colours()
        self._sync_keyboard_chrome()

    def follow_theme(self) -> None:
        """Draw in the `ui.theme` scheme, among those Textual's colours offer; a name not
        offered (pywal's before pywal writes its palette) keeps the scheme in use, with
        Textual's warning."""
        name = self.settings.ui.theme
        offered = offered_schemes(os.environ)
        if name not in offered:
            self.show_warning(f"Theme {name!r} is not available"
                              + (f": pywal has not written {WalFile.directory(os.environ) / WalFile.NAME}"
                                 if name == WalFile.SCHEME else ""), "Theme")
            return
        self.restyle(offered[name])

    def follow_line_renderer(self) -> None:
        self.renderer.follow(self.renderer.scheme, self.settings.diff)

    def restyle(self, scheme: ColourScheme) -> None:
        """Every colour from ``scheme`` and the `diff` settings: the palette and stylesheet
        pyqt-reactive applies to the whole application, then the renderer every widget
        holds, which repaints each widget's own colours (`QtLineRenderer.themed`)."""
        if scheme != self.renderer.scheme:
            self.theme.apply_color_scheme(ColorScheme.from_theme(scheme))
        self.renderer.follow(scheme, self.settings.diff)

    def follow_wheel_scroll_rows(self) -> None:
        QApplication.setWheelScrollLines(self.settings.ui.wheel_scroll_rows)

    def follow_key_mode(self) -> None:
        for editor in capability_widgets(self, ComposerEditor):
            editor.follow_key_mode()
            editor.composer.refresh_editing_mode()
        self.action_keys.follow()

    def follow_keymap(self) -> None:
        self.action_keys.follow()

    def show_session_tabs(self, shown: bool) -> None:
        self.paint_tabs()
        self.tab_column.setVisible(shown)
        self._nav_separators[2].setVisible(shown)

    def pane_open(self, identity: type[SidebarPlacement]) -> bool:
        """Read through SidebarLayout — the single collapsed-state owner. A collapsed
        bar means the pane is NOT open, so pane_open is `not is_collapsed`."""
        return not self.sidebar_layout.is_collapsed(identity)

    def _conversation_open(self) -> bool:
        return self.workspace_sessions.selected is not self.workspace_sessions.home

    def _pane_available(self, identity: type[SidebarPlacement]) -> bool:
        """The thread's settings follow an open conversation; the sidebar is always there."""
        return identity.available(self._conversation_open())

    def _pane_heading(self, identity: type[SidebarPlacement]) -> str:
        return identity.heading(self._viewed_titles())

    def _viewed_titles(self) -> Iterator[str]:
        """The viewed tab's title, as Textual's `SideBar.heading` reads it."""
        mode = self.selected_mode
        return (tab.title for tab in self.session_navigation.tabs if tab.mode_name == mode)

    def _bind_thread_pane(self) -> None:
        """The thread's settings follow the selected page: a conversation, or the welcome,
        which is a `NoConversationView`. A collapsed pane shows only its bar, so it follows the
        welcome until it opens (opening it lays the panes out again, which binds the selected
        page): binding a conversation lists its settings and binds its comms, plan and context
        panels, work every tab open and switch paid for a pane nobody saw. Following the
        welcome, not the last page, keeps no closed view behind the collapsed panels."""
        sessions = self.workspace_sessions
        collapsed = self.sidebar_layout.is_collapsed(ThreadSidebarPlacement)
        self.thread_pane.bind(sessions.home if collapsed else sessions.selected)

    def present_alone(self) -> None:
        """Show the welcome's parts in the comms sidebar while it holds the window; hide them
        when a tab is shown beside it."""
        alone = self.sidebar_layout.alone
        if alone == self.shown_alone:
            return
        self.shown_alone = alone
        for part in self.sole_parts:
            part.setVisible(alone)

    def present_panes(self) -> None:
        """Draw both sidebars from the one layout and place them; the thread's sidebar is
        presented only while a conversation is open."""
        self.tabs.sync_strip_width(self.tab_strip.viewport().width())
        self._bind_thread_pane()
        self.present_alone()
        for side in self.chrome.sidebars:
            side.present()
        self.chrome.arrange()

    def rearrange_sidebars(self) -> None:
        """A move, resize, float or fold: present the panes again, once per turn of the event
        loop however many grip moves arrived in it. A fold can change what the thread pane
        follows (`_bind_thread_pane`); a resize cannot, and binding the same view is free."""
        if not self._layout_pending:
            self._layout_pending = True
            QTimer.singleShot(0, self, self._present_pending)

    def _present_pending(self) -> None:
        self._layout_pending = False
        self.present_panes()

    def show_sidebar(self) -> None:
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, False)
        self.present_panes()

    def hide_sidebar(self) -> None:
        self.sidebar_layout.set_collapsed(ChannelsSidebarPlacement, True)
        self.present_panes()

    def begin_frontend(self) -> None:
        """The window opens as the platform opens windows; then the sidebar and welcome bind
        the observation the connection serves, and the shared start reopens the saved tabs,
        as the start a bus switch waits for. Moving to the background keeps the settings in
        use, since Android may end a backgrounded app without a quit."""
        host.open_window(self)
        QApplication.instance().applicationStateChanged.connect(self.application_state_changed)
        self.run_operation(ApplicationStart, self.start_frontend)

    async def start_frontend(self) -> None:
        await self.coordination_access.follow_sidebar(self.sidebar)
        await self.application.start()

    @property
    def app_focus(self) -> bool:
        """Textual's `App.app_focus`: whether the desktop has this app in front, which the
        notification policy (`notifications.system`) reads before a desktop notification."""
        return QApplication.applicationState() == Qt.ApplicationState.ApplicationActive

    def application_state_changed(self, state: Qt.ApplicationState) -> None:
        transition = PRESENCE_TRANSITIONS.get(state)
        if transition is not None:
            self._presence = transition(self._presence, self)

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
        self.navigation.show()
        self.bus_switcher.show_switcher()

    async def close_native_views(self) -> None:
        self.sidebar.retire_all()
        self.input_attention.close()
        await self.session_navigation.close_views()

    async def open_keymap_browser(self) -> None:
        """Qt override of `ClientApplication.open_keymap_browser`. Opens the
        shared-UX `QtKeymapScreen` modal; both frontends consume the same
        `KeymapBrowserState` so the browser logic lives once in
        `toad.client.keymap_browser`."""
        from toad.qt.keymap_screen import QtKeymapScreen
        focused: frozenset[KeyInvocationId] = frozenset()
        dialog = QtKeymapScreen(self, focused)
        dialog.show()

    async def edit_settings(self) -> None:
        """Qt override of `ClientApplication.edit_settings`: the settings screen both
        frontends inherit (`SettingsEditing`), drawn in Qt; it writes the settings file
        when it closes, as Textual's does."""
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
        access = self.coordination_access
        selected = access.selected(access.observation.observed().root)
        QtTransferDialog.for_kind(kind)(self, selected, parent=self).show()

    def start_transfer_task(self, request: Transfer, selected) -> None:
        """Qt analog of Textual's `run_worker(..., exclusive=True)`: cancel any
        running task of this transfer kind, then schedule the new one on the
        running loop. Keeps the shared `TransferRequest.execute` on the UI
        thread's event loop (its internal `preparation.run_thread` hop keeps
        the CPU work off the GIL)."""
        kind = type(request)
        existing = self._transfer_tasks.get(kind)
        if existing is not None and not existing.done():
            existing.cancel()
        self._transfer_tasks[kind] = asyncio.ensure_future(request.execute(self, selected))

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
        self.menu_panel.show_entries(self._application_menu_entries(), QtMenu.anchor_of(self.menu))

    def _reopen_menu(self) -> None:
        self.menu_panel.show_entries(self._application_menu_entries(), QtMenu.anchor_of(self.menu))

    def open_text_size_control(self) -> None:
        """Open the nested message text-size control inside `self.menu_panel` with 5% steps
        and direct numeric percentage entry (50-200%)."""
        panel = QWidget(self.menu_panel)
        row = QHBoxLayout(panel)
        row.setContentsMargins(UiGap.dialog, UiGap.normal, UiGap.dialog, UiGap.normal)
        row.setSpacing(UiGap.normal)

        spin = QSpinBox(panel)
        spin.setRange(50, 200)
        spin.setSingleStep(5)
        spin.setSuffix("%")
        spin.setValue(self.settings.ui.message_font_scale)
        spin.setMinimumHeight(40)
        spin.valueChanged.connect(self.set_message_font_scale)

        minus = QtPushButton("−", panel)
        minus.setMinimumSize(44, 40)
        minus.clicked.connect(lambda: spin.setValue(max(50, spin.value() - 5)))

        plus = QtPushButton("+", panel)
        plus.setMinimumSize(44, 40)
        plus.clicked.connect(lambda: spin.setValue(min(200, spin.value() + 5)))

        reset = QtPushButton("100%", panel)
        reset.setMinimumSize(56, 40)
        reset.clicked.connect(lambda: spin.setValue(100))

        row.addWidget(minus)
        row.addWidget(spin, 1)
        row.addWidget(plus)
        row.addWidget(reset)
        self.menu_panel.show_panel(
            "Text size", panel, back=self._reopen_menu, anchor=QtMenu.anchor_of(self.menu)
        )

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

    def run_menu_action(self, work) -> None:
        """Schedule a menu command on this app's tracked MenuActionRun lane."""
        self.run_operation(MenuActionRun, work)

    def offer_entries(self, entries: tuple[MenuEntry, ...], anchor: QRect | None = None) -> None:
        """Rich-row API: callers that have `MenuEntry` with keybindings and descriptions
        (the hamburger menu, the row-context menu) populate the shared QtMenu directly, at
        `anchor` in this window's coordinates (where they were asked from)."""
        self.menu_panel.show_entries(entries, anchor)

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
        self.navigation.show()
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

    def make_opening_view(self, request, origin, identity):
        """Qt's thread-navigation opening placeholder: a `QtOpeningSessionView` (not
        Textual's `MainScreen.opening(...)`). Lazy-import `QtOpeningSessionView` to
        keep `toad.qt.window` import-light at module load. Textual's override lives at
        `src/toad/app.ToadApp.make_opening_view`."""
        return QtOpeningSessionView(request.target, self.renderer, self.animation_clock)

    def thread_view(self, prepared):
        """The `QtMailboxView` a sidebar open swaps in, bound to the thread as Textual's
        `MainScreen.from_thread` binds its screen."""
        view = QtMailboxView(self, prepared.project, prepared.thread.incarnation, prepared.root)
        view.bind_thread(prepared.thread.incarnation, prepared.root)
        return view

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
        bound = QtMailboxView(self, prepared.project, prepared.thread.incarnation, prepared.root)
        bound.id = opening_view.id
        self.workspace_sessions.swap_page(opening_view, bound)
        return bound

    def visit_index(self, index: int) -> None:
        self.switch(self.session_navigation.tabs[index].mode_name, self.tab_order.record_visit)

    def close_index(self, index: int) -> None:
        self.close_session(self.session_navigation.tabs[index].mode_name)

    def offer_tab_menu(self, point: QPoint) -> None:
        """The tab under a right-click or a held finger offers the shared tab menu."""
        index = self.tabs.tabAt(point)
        if index >= 0:
            self.offer_entries(QtTabAt(self, self.session_navigation.tabs[index].mode_name).menu_entries())

    def move_index(self, start: int, end: int) -> None:
        """A tab dragged from one place in the bar to another: it moves past the tab it
        displaced in the shared order, which also holds saved tabs this window has not
        opened, and the bar draws that order again."""
        tabs, order = self.session_navigation.tabs, self.tab_order.names
        moved, displaced = tabs[start], tabs[end].identity
        self.session_navigation.events.publish(session_requests.SessionMove(
            moved.mode_name, order.index(displaced) - order.index(moved.identity)))

    def _handle_back_shortcut(self) -> None:
        if QApplication.activePopupWidget() is None:
            self.go_back()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if (event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Back)
                and QApplication.activePopupWidget() is None):
            event.accept()
            self.go_back()
            return
        super().keyPressEvent(event)

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
