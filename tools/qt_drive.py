"""Drive the Qt client offscreen against a live bus and print what it shows.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/qt_drive.py SCENARIO OUTDIR --comms-profile PROFILE
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/qt_drive.py SCENARIO OUTDIR --comms-root ROOT

The Core is selected as `toad.qt.main` selects it: PROFILE is a UI profile
(~/.local/state/agent-comms/ui-profiles/NAME.json), ROOT a bus root this machine opens
directly (the connection agent processes start under); OUTDIR gets a screenshot per step.
Each scenario opens the client exactly as `toad.qt.client_start.serve` does
and prints the state a reader would see, so two runs (before and after a change) compare
line by line. This is the real-application check for the phone client; tests cannot see
what the window draws.
"""

from __future__ import annotations

import asyncio
import time
import os
import sys
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from collections.abc import Callable
from typing import ClassVar

import qasync
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QInputMethodEvent, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QDialog, QLabel, QScroller, QStyleOptionViewItem, QApplication, QPushButton, QWidget

from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.registry.thread_presentation import LiveThreadOwnerBinding
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.message_category import MessageCategory
from objectstate import DottedFieldPath
from toad.qt.frame_probe import FrameProbe, ProbedApplication
from toad.client.application import BusDiscovery
from toad.client.application_actions import (
    ApplicationAction, NewSessionAction, NewThreadAction, QuitAction, SettingsAction,
)
from toad.qt.settings_screen import QtSettingsScreen
from toad.client.bus_submission import TypedText
from toad.client.conversation import ChannelConversation
from toad.client.connection import CoreConnection
from toad.client.local_connection import select_connection
from toad.client.line_blocks import LineLink
from toad.qt.client_start import open_app
from toad.qt.glyph_fonts import install_glyph_fonts
from toad.qt.theme import current_scheme, offered_schemes
from toad.qt.finger_press import FingerPress
from toad.qt.finger_scrolling import FingerScrollGesture, FingerScrolling, TouchAsMouse
from toad.goal_interactions.controls import CollapseInteraction, HistoryInteraction
from pyqt_reactive.widgets.fitted_text import WrappedText
from toad.qt.goal import QtGoalBar, QtGoalHistory
from toad.qt.prompt_stack import QtInputDeliveryDetails, QtStatusLine
from toad.key_modes import KeyMode
from toad.keymap import KeymapRow
from toad.reader_actions import PageDownAction
from toad.preferences import SETTINGS, SavedSettings
from toad.setting_declarations import Effect, FamilyChoices
from formbridge.forms.declared_fields import DeclaredField
from ui_theme.catalog import SCHEMES
from textual.geometry import Offset
from toad.qt.name_wave import TabGhost, TabGrowth
from toad.qt.side_bar import PaneSlide, QtSidebarAction
from toad.sidebar_layout import DirectionalSidebarPlacementAction, FloatSidebarPlacementAction
from toad.sidebar_placement import (
    BottomSidebarEdge,
    ChannelsSidebarPlacement,
    SidebarEdge,
    ThreadSidebarPlacement,
    TopSidebarEdge,
)
from toad.client.history import ChannelDestination, WirePageBuffer
from toad.qt.command_form import QtCommandDialog
from toad.qt.keymap_screen import QtKeymapScreen
from toad.qt.opening_view import QtOpeningSessionView
from toad.thread_sidebar_declarations import panel_specs_for_view
from toad.client.bus_submission import ConversationSubmission
from toad.setting_choices import CenterColumnAlignment, HiddenScrollbar, TransientScrollbar
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle
from toad.client.input_modality import KeyboardInput, TouchInput
from toad.qt.float_layer import QtFloatLayer, QtNoticeCard
from toad.qt.menu import QtMenuRow
from toad.qt.activity import ChannelActivity
from toad import paths
from toad.qt.thread_comms_panel import QtThreadCommsPanel
from toad.qt.window import ConversationRow, ConversationView, MenuActionRun, QtToadApp
from toad.conversation_turn import LocalTurnBinding
from toad.core.events import TextAgentFail, UnsupportedResumeAgentFail
from toad.live_output import ResponseStream, ThoughtStream
from toad.qt.history import HistoryRows
from toad.qt.overlay_scrollbar import OverlayScrollBar
from toad.qt.live_turn import QtLiveFragment

PROJECT = Path(__file__).resolve().parents[1]


async def until(check, label: str, tenths: int = 200) -> None:
    for _ in range(tenths):
        await asyncio.sleep(0.1)
        if check():
            return
    raise TimeoutError(label)


class StrayWindows(QObject):
    """Every widget shown as its own top-level window, other than the app window and real
    popups/dialogs. On Android each one gets its own native window and EGL surface, which
    deadlocks against the accessibility bridge (SIGABRT "Failed to acquire deadlock
    protector … eglSurface()"). A widget made visible before it has a parent becomes one,
    even if a layout reparents it a moment later — so this watches Show as it happens; the
    desktop never crashes on it, and the drive fails loudly instead."""

    ALLOWED = (Qt.WindowType.Popup, Qt.WindowType.ToolTip, Qt.WindowType.Dialog, Qt.WindowType.Sheet)
    seen: ClassVar[list[str]] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow()
                and type(watched).__name__ != "QtToadApp" and watched.windowType() not in self.ALLOWED):
            StrayWindows.seen.append(f"{type(watched).__module__}.{type(watched).__qualname__}")
        return False

    @classmethod
    def require_none(cls, step: str) -> None:
        if cls.seen:
            raise AssertionError(f"{step}: widgets shown as their own top-level windows: {sorted(set(cls.seen))}")


class Scenario(DeclaredFamily, ABC, affix="Scenario"):
    """One walk through the client; its declared name is the command-line word."""

    summary: ClassVar[str]

    @classmethod
    def finger_gesture(cls) -> FingerScrollGesture:
        """The drag this drive's scroll areas answer: this platform's, unless the walk is a
        phone's."""
        return FingerScrollGesture.of_platform()

    @classmethod
    def before_open(cls) -> None:
        """Run before the client opens, to watch what it does from its first frame."""

    def __init__(self, app: QtToadApp, out: Path) -> None:
        self.app = app
        self.out = out

    @property
    def page(self):
        return self.app.workspace_sessions.pages.currentWidget()

    def tabs(self) -> list[str]:
        return [self.app.tabs.tabText(index) for index in range(self.app.tabs.count())]

    def report(self, step: str, **facts: object) -> None:
        StrayWindows.require_none(step)
        shown = " ".join(f"{name}={value!r}" for name, value in facts.items())
        print(f"{step}: page={type(self.page).__name__} "
              f"sidebar={'up' if self.app.sidebar.isVisible() else 'down'} tabs={self.tabs()} {shown}",
              flush=True)
        self.app.grab().save(str(self.out / f"{type(self).declared_name}-{step}.png"))

    async def expand(self, *keys: str) -> None:
        """Open these sidebar groups as a tap would, then redraw the sidebar: the groups
        stay open across the redraw."""
        for item in self.app.sidebar.items():
            item.setExpanded(item.key in keys or item.isExpanded())
        self.app.sidebar.present()
        await asyncio.sleep(0.3)

    async def type(self, text: str) -> None:
        """Type into the current conversation's composer as a person would."""
        composer = self.page.composer
        composer.editor.clear()
        composer.editor.setFocus()
        composer.editor.insertPlainText(text)
        await asyncio.sleep(0.2)

    async def open(self, row, label: str) -> None:
        """Open a sidebar row and wait for its conversation to draw."""
        before = self.page
        self.app.open_row(row)
        # The opening view stands in until the conversation's own view replaces it.
        await until(lambda: self.page is not before and self.page is not self.app.workspace_sessions.home
                    and not isinstance(self.page, QtOpeningSessionView)
                    and self.page.messages.model_rows.rowCount(), label)
        await asyncio.sleep(1.5)

    async def open_named(self, name: str) -> None:
        """Open a #channel or a thread from its sidebar row; a thread row sits under each
        channel it belongs to, and any one opens it."""
        await self.listed()
        if name.startswith("#"):
            await self.channel_row(name)
            await self.expand(name)
            await self.open(await self.channel_row(name), name)
        else:
            await self.open(await self.found(lambda row: isinstance(row, ConversationRow)
                                             and row.target.name == name, name), name)
        await asyncio.sleep(2.0)

    async def found(self, wanted, label: str, rows=None, tenths: int = 200):
        """The first sidebar row that is `wanted`, waited for: the sidebar is a live list,
        filled from observations that can arrive after the step that reads it (the welcome's
        first rows come before the channels). It is read again every tenth of a second
        through the loop the scenario's steps run on, until the deadline, and then the drive
        fails naming the missing row and every row listed. `rows` reads the rows to search,
        every row nested under every channel unless it is given."""
        read = rows or (lambda: self.rows(self.app.sidebar.items()))
        present: list = []
        for _ in range(tenths):
            present = list(read())
            for row in present:
                if wanted(row):
                    return row
            await asyncio.sleep(0.1)
        listed = ", ".join(f"{row.drawn[1] or row.key!r}" for row in present) or "nothing"
        raise LookupError(f"the sidebar lists no {label} after {tenths / 10:.1f} s; it lists: {listed}")

    async def channel_row(self, name: str) -> ConversationRow:
        """The channel's top-level row, once the sidebar lists it."""
        return await self.found(lambda row: isinstance(row, ConversationRow) and row.target.name == name,
                                f"channel {name}", rows=self.app.sidebar.items)

    def rows(self, items):
        """Every sidebar row, threads nested under their channels included."""
        for item in items:
            yield item
            yield from self.rows(item.child(index) for index in range(item.childCount()))

    def thread_rows(self) -> list[ConversationRow]:
        """Every thread row the sidebar lists, each once."""
        threads = self.app.coordination_access.observation.observed().sidebar.threads.rows
        found: dict[str, ConversationRow] = {}
        for row in self.rows(self.app.sidebar.items()):
            if isinstance(row, ConversationRow) and row.key in threads:
                found.setdefault(row.key, row)
        return list(found.values())

    async def thread_row(self) -> ConversationRow:
        """The first thread nested under a channel, as the Textual sidebar nests them."""
        channel = await self.found(lambda row: isinstance(row, ConversationRow) and row.childCount() > 0,
                                   "channel with a thread under it", rows=self.app.sidebar.items)
        self.app.sidebar.expandItem(channel)
        return channel.child(0)

    async def listed_thread(self, key: str) -> ConversationRow:
        """The thread row for `key`, once the sidebar lists it."""
        return await self.found(lambda row: row.key == key, f"thread {key}", rows=self.thread_rows)

    async def live_native_thread_rows(self) -> list[ConversationRow]:
        """The listed threads a running native runtime owns, as Core presents each owner
        binding: only a live native owner is offered the configure form (an external CLI's
        thread is bus-held; a native thread whose owner is not running has none to ask)."""
        root = str(self.app.source().root)
        rows = []
        for row in self.thread_rows():
            read = await self.app.coordination_access.transcripts.thread_presentation(root, row.target.name)
            if type(read.raised().binding) is LiveThreadOwnerBinding:
                rows.append(row)
        return rows

    def offered(self, count: int) -> list[str]:
        return [offer.layout.name.text for offer in self.page.composer.offers.offers[:count]]

    async def listed(self) -> None:
        """The bus has answered: the welcome lists at least one row."""
        await until(lambda: sum(section.childCount() for section in self.app.workspace_sessions.home.rows.items()) > 0,
                    "welcome rows")

    @abstractmethod
    async def run(self) -> None: ...


class TabsScenario(Scenario):
    summary = "open #comms and a DM, back, forward, close a tab; print the saved roster"

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.expand("#comms")
        comms = await self.channel_row("#comms")
        peer = await self.thread_row()
        app.open_row(comms)
        await until(lambda: self.page is not app.workspace_sessions.home and self.page.messages.model_rows.rowCount(), "#comms")
        self.report("1-comms")
        app.open_row(peer)
        await until(lambda: app.tabs.count() == 2, "peer")
        await asyncio.sleep(1.5)
        self.report("2-peer")
        app.back.click()
        await asyncio.sleep(1.0)
        self.report("3-back")
        app.forward.click()
        await asyncio.sleep(1.0)
        self.report("4-forward")
        app.close_index(app.tabs.currentIndex())
        await until(lambda: app.tabs.count() == 1, "close")
        await asyncio.sleep(0.5)
        self.report("5-closed")
        saved = await (await app.get_db()).tab_list(app.tab_order.scopes)
        print("roster:", [identity.mode_name for identity in app.tab_order.names],
              "saved:", [row.identity.mode_name for row in saved], flush=True)


class TabStripScenario(Scenario):
    summary = ("at phone width, open COUNT (6) sidebar threads as tabs: the strip scrolls instead of "
               "squeezing them, no tab's title is cut short, the selected tab is in view, and a "
               "right-click (a held finger) on a tab offers Move left/right and Close tab; Move right "
               "moves it past its neighbour")

    async def run(self) -> None:
        app = self.app
        app.resize(412, 915)
        await self.listed()
        count = int(os.environ.get("COUNT", "6"))
        await self.expand("#comms")
        await until(lambda: len(self.thread_rows()) >= 3, "three sidebar threads")
        rows = self.thread_rows()[:count]
        for opened, row in enumerate(rows, 1):
            app.open_row(row)
            await until(lambda: app.tabs.count() >= opened, f"tab {opened}")
        await asyncio.sleep(1.5)
        strip, tabs = app.tab_strip, app.tabs
        titles = [tabs.tabText(index) for index in range(tabs.count())]
        cut = [title for index, title in enumerate(titles)
               if tabs.fontMetrics().horizontalAdvance(title) > tabs.tabRect(index).width()]
        scrolls = strip.horizontalScrollBar().maximum()
        current = tabs.tabRect(tabs.currentIndex())
        seen = strip.viewport().rect().translated(strip.horizontalScrollBar().value(), 0)
        self.report("1-many-tabs", tabs=len(titles), strip_scrolls=scrolls, cut=cut[:3],
                    selected_in_view=seen.contains(current.center()))
        assert scrolls > 0, "the tabs were squeezed into the strip instead of scrolling"
        assert not cut, f"tab titles cut short: {cut[:3]}"
        assert seen.contains(current.center()), "the selected tab is scrolled out of view"
        first = tabs.tabData(0)
        tabs.customContextMenuRequested.emit(tabs.tabRect(0).center())
        await asyncio.sleep(0.4)
        offered = [row.label.text() for row in app.menu_panel.findChildren(QtMenuRow)]
        self.report("2-tab-menu", offered=offered)
        assert offered == ["Move right", "Close tab"], f"first tab offered {offered}"
        next(row for row in app.menu_panel.findChildren(QtMenuRow) if row.label.text() == "Move right")._fire()
        await until(lambda: tabs.tabData(1) == first, "the first tab moved right")
        self.report("3-moved", order=[tabs.tabData(index) for index in range(tabs.count())][:4])


class ActivityScenario(Scenario):
    summary = "open a working thread's DM (else the first thread); print its info row and activity"

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.found(lambda row: True, "thread row", rows=self.thread_rows)
        rows = app.coordination_access.observation.observed().sidebar.threads.rows
        children = self.thread_rows()
        working = [row for row in children if rows[row.key].status.is_working()]
        peer = (working or children)[0]
        app.open_row(peer)
        await until(lambda: self.page is not app.workspace_sessions.home
                    and getattr(self.page, "composer", None) is not None
                    and self.page.composer.info_bar.status.text(), "status")
        await asyncio.sleep(1.0)
        SurroundScenario.report_surround(self, "1-opened", peer=peer.key)


class ParticipantSteps(Scenario, declared_name=None):
    """A finger tapping a channel's `N active` line and a thread row the way a phone can,
    and every notice the client posts from its first frame, so a step can fail on one."""

    notices: ClassVar[list[tuple[str, str]]]

    @classmethod
    def before_open(cls) -> None:
        cls.notices = []
        posted = QtFloatLayer.post

        def recorded(layer, text: str, role, seconds: float) -> None:
            cls.notices.append((role.name, text))
            posted(layer, text, role, seconds)
        QtFloatLayer.post = recorded

    def failures_since(self, count: int) -> list[str]:
        """The warning and error notices posted after the first ``count``."""
        return [f"{role}: {text}" for role, text in self.notices[count:] if role in ("WARNING", "ERROR")]

    def activity(self) -> ChannelActivity:
        found = self.page.findChildren(ChannelActivity)
        if not found:
            raise LookupError(f"{type(self.page).__name__} shows no channel activity line")
        return found[0]

    async def finger_tap(self, widget: QWidget, point: QPoint) -> None:
        FingerScenario.press(widget, QEvent.Type.MouseButtonPress, point, True)
        await asyncio.sleep(0.05)
        FingerScenario.press(widget, QEvent.Type.MouseButtonRelease, point, False)
        await asyncio.sleep(0.8)

    async def tap_activity(self, label: str) -> None:
        """Open the channel's activity line, tap a listed member, and close it again."""
        line = self.activity()
        heading = QPoint(line.width() // 3, line.fontMetrics().height() // 2)
        self.report(f"{label}-shown", text=self.activity_text(line), height=line.height())
        await self.finger_tap(line, heading)
        self.report(f"{label}-opened", open=line.shown.details_open, members=len(line.members),
                    height=line.height())
        if line.members:
            await self.finger_tap(line, QPoint(heading.x(), line.height() - heading.y()))
            self.report(f"{label}-member-tapped", open=line.shown.details_open)
        if line.shown.details_open:
            await self.finger_tap(line, heading)
        self.report(f"{label}-closed", open=line.shown.details_open)

    @staticmethod
    def activity_text(line: ChannelActivity) -> str:
        document = QTextDocument()
        document.setHtml(line.text())
        return document.toPlainText()

    async def open_twice(self, row: ConversationRow) -> None:
        """A row tapped twice, as a phone can deliver one tap, or a second tap while the
        first opening mounts: both open from home, and the second lands on the same tab."""
        self.app.open_row(row)
        await asyncio.sleep(0.05)
        self.app.open_row(row)
        await until(lambda: getattr(self.page, "thread_identity", None) is not None
                    and self.page.thread_identity.thread_name() == row.target.name, row.target.name)
        await asyncio.sleep(3.0)
        named = sum(row.target.name in tab for tab in self.tabs())
        if named != 1:
            raise AssertionError(f"{row.target.name} is open in {named} tabs after a double tap")


class ParticipantsScenario(ParticipantSteps):
    summary = ("at a Pixel 8a's width, by finger: tap #comms' and a second channel's `N active` "
               "line open, a listed member, and closed; open a thread, then tap a thread row twice "
               "as a phone can; fails on any warning or error notice, and on one that saved no file")

    @classmethod
    def finger_gesture(cls) -> FingerScrollGesture:
        return TouchAsMouse()

    async def run(self) -> None:
        await self.open_named("#comms")
        await self.tap_activity("1-comms")
        other = await self.found(lambda row: isinstance(row, ConversationRow) and row.target.name.startswith("#")
                                 and row.target.name != "#comms", "a second channel", rows=self.app.sidebar.items)
        await self.open(other, other.target.name)
        await self.tap_activity("2-channel")
        peer = await self.thread_row()
        await self.open(peer, peer.target.name)
        await self.open_named("#comms")
        await self.open_twice(peer)
        self.report("3-double-tap", tabs=self.tabs())
        saved = [*paths.get_errors().iterdir(), *paths.get_warnings().iterdir()]
        print("notices:", self.notices, "saved:", sorted(path.name for path in saved), flush=True)
        failures = self.failures_since(0)
        if len(saved) < len(failures):
            raise AssertionError(f"{len(failures)} warning/error notice(s) but {len(saved)} saved: {failures}")
        if failures:
            raise AssertionError(f"{len(failures)} warning/error notice(s): {failures}")


class SurroundScenario(Scenario):
    summary = ("open a thread (PEER env, else the first working one) on a Pixel 8a and print every "
               "row between its transcript and the tab bar, in Textual's PromptStack order")

    width: ClassVar[int] = 412

    @staticmethod
    def sweep_extent(view, sweep) -> object:
        """The sweep row's width beside its view's, and the share of the row the paint inks,
        rendered at the screen's device pixel ratio (a phone's 2.625 is where a logical image
        drew at 1/ratio of the row)."""
        if sweep is None:
            return None
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QImage, QPainter, QRegion
        from PySide6.QtWidgets import QWidget
        # Measured painting, whether or not the thread works right now: geometry is the
        # question, and the live answer is put back after the render.
        working = sweep.working
        sweep.sweep(True)
        ratio = sweep.devicePixelRatioF() or 1.0
        image = QImage(round(sweep.width() * ratio), round(sweep.height() * ratio),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(0)
        painter = QPainter(image)
        sweep.render(painter, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        painter.end()
        sweep.sweep(working)
        inked = [x for x in range(image.width())
                 if any(image.pixelColor(x, y).alpha() for y in range(0, image.height(), 2))]
        span = (round(inked[0] / image.width(), 3), round((inked[-1] + 1) / image.width(), 3)) if inked else None
        return {"row": sweep.width(), "view": view.width(), "ratio": ratio, "inked": span,
                "working": working}

    def report_surround(self, step: str, **facts: object) -> None:
        """Each row Textual's `Conversation.compose` mounts under its window, as Qt shows it."""
        view = self.page

        def row(name):
            widget = getattr(view, name, None)
            return "absent" if widget is None else ("shown" if widget.isVisible() else "hidden")

        composer = view.composer
        info = composer.info_bar if composer is not None else None
        goal = getattr(view, "goal_bar", None)
        details = getattr(view, "thread_activity", None)
        sweep = getattr(view, "agent_activity", None)
        self.report(
            step, **facts,
            flash=(row("feedback"), view.feedback.text() if view.feedback.isVisible() else ""),
            sweep=(row("agent_activity"), sweep is not None and hasattr(sweep, "working") and sweep.working),
            sweep_extent=SurroundScenario.sweep_extent(view, sweep),
            working=view.working() if hasattr(view, "working") else None,
            status_title=(row("thread_activity"), details.title.text() if hasattr(details, "title") else ""),
            goal=(row("goal_bar"), goal.header.text() if goal is not None else "",
                  [control.text() for control in goal.actions if control.isVisible()] if goal is not None else []),
            composer=(composer is not None and composer.isVisible(),
                      composer.glyph.text() if composer else "", composer.editor.placeholderText() if composer else "",
                      bool(composer and composer.findChildren(QPushButton))),
            info_bar=(info.path.text(), info.status.text(), info.badge.text()) if info else None,
            editing=(composer.editor.editing_mode.label, composer.editor.hasFocus()) if composer else None,
            rows=view.messages.model_rows.rowCount())

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(int(os.environ.get("WIDTH", self.width)), 915)
        if mode := os.environ.get("KEY_MODE"):
            # As a person choosing "Keyboard mode" on the settings screen: the one setting
            # both frontends' prompts read.
            app.saved_settings.set(SETTINGS.ui.key_mode, KeyMode.member_named(mode))
        # The welcome answers before the sidebar has drawn its thread rows.
        await self.found(lambda row: True, "thread row", rows=self.thread_rows)
        rows = app.coordination_access.observation.observed().sidebar.threads.rows
        children = self.thread_rows()
        print("working:", [row.key for row in children if rows[row.key].status.is_working()], flush=True)
        wanted = os.environ.get("PEER")
        peer = next((row for row in children if row.key == wanted), None) if wanted else None
        if peer is None:
            peer = next((row for row in children if rows[row.key].status.is_working()), children[0])
        home = app.workspace_sessions.home
        app.open_row(peer)
        await until(lambda: self.page is not home and getattr(self.page, "composer", None) is not None, "composer")
        await until(lambda: self.page.messages.model_rows.rowCount(), "transcript", tenths=150)
        await asyncio.sleep(4.0)
        self.report_surround("1-opened", peer=peer.key)
        self.page.flash_success("Agent Comms connected")
        await asyncio.sleep(0.3)
        self.report_surround("2-flash", peer=peer.key)
        details = self.page.thread_activity
        details.toggle()
        await asyncio.sleep(0.3)
        self.report_surround("3-details-open", peer=peer.key, details=details.details.text()[:120],
                             inspect=details.inspect_action.isVisible())
        details.inspect_action.click()
        await until(lambda: app.findChild(QtInputDeliveryDetails) is not None, "session details")
        await asyncio.sleep(0.3)
        dialog = app.findChild(QtInputDeliveryDetails)
        dialog.grab().save(str(self.out / "surround-3b-session-details.png"))
        print("3b-session-details:", [line.text()[:80] for line in dialog.findChildren(WrappedText) if line.isVisible()],
              flush=True)
        dialog.reject()
        details.toggle()
        app.activateWindow()
        self.page.composer.editor.setFocus()
        await asyncio.sleep(0.3)
        self.report_surround("4-focused", peer=peer.key)


class QueueScenario(SurroundScenario):
    summary = ("open PEER (a scratch CLI thread) and walk its queue as the TUI shows it: the delivery "
               "controls and queue summary on open, after two sends through the composer, and after "
               "Send now; print the thread's owner binding and goal bar")

    def report_queue(self, step: str) -> None:
        view = self.page
        composer = view.composer
        self.report(
            step,
            controls=(composer.delivery_controls.isVisible(), composer.offers_send_now,
                      composer.agent_ready, composer.holds_input),
            summary=composer.submitting.text() if composer.submitting.isVisible() else "",
            goal=(view.goal_bar.isVisible(), view.goal_bar.header.text()) if view.goal_bar is not None else None,
            rows=view.messages.model_rows.rowCount())

    async def send(self, text: str, now: bool = False) -> None:
        editor = self.page.composer.editor
        editor.setPlainText(text)
        if now:  # the delivery row's Send now label, pressed as a reader taps it
            from toad.qt.queue_ui import QtSendNow
            QTest.mouseClick(self.page.composer.delivery_controls.findChild(QtSendNow), Qt.MouseButton.LeftButton)
        else:
            self.page.composer.submit()
        await asyncio.sleep(0.4)

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(int(os.environ.get("WIDTH", self.width)), 915)
        wanted = os.environ["PEER"]
        peer = await self.listed_thread(wanted)
        home = app.workspace_sessions.home
        app.open_row(peer)
        await until(lambda: self.page is not home and getattr(self.page, "composer", None) is not None, "composer")
        await until(lambda: self.page.messages.model_rows.rowCount(), "transcript", tenths=150)
        await asyncio.sleep(4.0)
        self.report_queue("1-opened")
        stamp = time.strftime("%H:%M:%S")
        await self.send(f"queue probe A {stamp}")
        await self.send(f"queue probe B {stamp}")
        self.report_queue("2-queued-two")
        await asyncio.sleep(4.0)
        self.report_queue("3-after-delivery")
        await self.send(f"queue probe now {stamp}", now=True)
        await asyncio.sleep(4.0)
        self.report_queue("4-sent-now")


class DraftScenario(SurroundScenario):
    summary = ("open PEER (a CLI thread mid-turn) and wait up to DRAFT_WAIT seconds for Core's CLI draft; "
               "report the draft rows the history window draws after the committed rows, and screenshot it")

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(int(os.environ.get("WIDTH", self.width)), 915)
        wanted = os.environ["PEER"]
        peer = await self.listed_thread(wanted)
        home = app.workspace_sessions.home
        app.open_row(peer)
        await until(lambda: self.page is not home and getattr(self.page, "composer", None) is not None, "composer")
        await until(lambda: self.page.messages.model_rows.rowCount(), "transcript", tenths=150)
        window = self.page.messages
        deadline = time.monotonic() + float(os.environ.get("DRAFT_WAIT", "240"))
        seen = 0
        while time.monotonic() < deadline:
            if window.draft:
                seen += 1
                await asyncio.sleep(1.5)
                self.report(f"{seen}-draft", draft=[(type(fragment).__name__, len(fragment.events),
                                                     fragment.clipboard_text[:60]) for fragment in window.draft],
                            last_rows=[type(window.model_rows.fragments[-index]).__name__ for index in (2, 1)],
                            rows=window.model_rows.rowCount())
                if seen >= 2:
                    return
                await asyncio.sleep(4.0)
            await asyncio.sleep(0.5)
        self.report("no-draft", rows=window.model_rows.rowCount())


class TranscriptScenario(Scenario):
    summary = ("open the thread or #channel named by TOAD_DRIVE_THREAD; paint every row opened; "
               "print each fragment's blocks; screenshot closed, opened and at the newest header")

    async def run(self) -> None:
        await self.open_named(os.environ.get("TOAD_DRIVE_THREAD", "personal-model-curation"))
        window = self.page.messages
        fragments = window.model_rows.fragments
        for fragment in fragments[-25:]:
            kinds = [type(block).__name__ for block in fragment.line_blocks]
            print(f"  {type(fragment).__name__:32} {kinds}", flush=True)
        self.report("1-opened", rows=len(fragments), links=window.rows.links_revision,
                    references=type(window.rows.renderer.links.references).__name__)
        # Every fragment opened, painted by the window's own renderer: an expanded tool call
        # draws the diff and terminal-output blocks a collapsed one never reaches.
        renderer = window.rows.renderer.at_width(window.viewport().width(), window.font())
        opened = [fragment for fragment in fragments if fragment.has_details]
        drawn = {type(block).__name__ for fragment in opened
                 for block in fragment.blocks(fragment.shown.toggled()) if renderer.html((block,))}
        print(f"opened {len(opened)} fragments; painted block kinds {sorted(drawn)}", flush=True)
        for fragment in opened[-3:]:
            fragment.request_show(fragment.shown.toggled())
        window.show_pages()
        await asyncio.sleep(1.5)
        self.report("2-details-open", rows=len(fragments))
        for fragment in opened[-3:]:
            fragment.request_show(fragment.shown.toggled())
        window.show_pages()
        # The newest message whose header names TOAD_DRIVE_HEADER (any header by default).
        named = os.environ.get("TOAD_DRIVE_HEADER", "")
        headed = max(row for row, fragment in enumerate(fragments)
                     if any(type(block).__name__ == "Divider" and named in block.label for block in fragment.line_blocks))
        last = window.model_rows.index(headed)
        window.scrollTo(last, window.ScrollHint.PositionAtTop)
        await asyncio.sleep(1.5)
        self.report("3-newest-header", rows=len(fragments))


class SurveyScenario(Scenario):
    summary = "open every thread in turn; print the block kinds its rows draw with details open"

    async def run(self) -> None:
        await self.listed()
        pending, names = list(self.app.sidebar.items()), []
        while pending:
            item = pending.pop()
            pending.extend(item.child(index) for index in range(item.childCount()))
            if isinstance(item, ConversationRow) and not item.target.name.startswith("#"):
                names.append(item.target.name)
        only = set(filter(None, os.environ.get("TOAD_DRIVE_THREADS", "").split(",")))
        for name in dict.fromkeys(name for name in names if not only or name in only):
            try:
                await self.open_named(name)
            except Exception as error:  # a thread that cannot open is reported, never skipped silently
                print(f"survey {name}: cannot open: {error!r}", flush=True)
                continue
            fragments = self.page.messages.model_rows.fragments
            kinds = sorted({type(block).__name__ for fragment in fragments
                            for block in fragment.blocks(fragment.shown.toggled())})
            parts = sorted({type(part).__name__ for fragment in fragments
                            for part in getattr(fragment, "output_parts", ())})
            print(f"survey {name}: rows={len(fragments)} kinds={kinds} tool parts={parts}", flush=True)


class ChannelTreeScenario(Scenario):
    summary = "the welcome and the channels sidebar with #any open, at the phone's width and then 1100px wide"

    async def run(self) -> None:
        await self.listed()
        await self.expand("#any")
        await asyncio.sleep(1.0)
        self.report("1-narrow")
        self.app.resize(1100, 900)
        await asyncio.sleep(1.5)
        self.report("2-wide")


class ToolDetailScenario(Scenario):
    summary = ("open TOAD_DRIVE_THREAD, read older pages until a tool call whose details draw "
               "TOAD_DRIVE_BLOCK (Patch or RichTextBody), open it at the top, screenshot")

    async def run(self) -> None:
        await self.open_named(os.environ.get("TOAD_DRIVE_THREAD", "claude-a"))
        wanted = os.environ.get("TOAD_DRIVE_BLOCK", "Patch")
        window = self.page.messages

        def found():
            return next((fragment for fragment in reversed(window.model_rows.fragments) if fragment.has_details
                         and any(type(block).__name__ == wanted
                                 for block in fragment.blocks(fragment.shown.toggled()))), None)

        for _ in range(30):
            if found() is not None:
                break
            before = window.model_rows.fragments[0].key
            window.scroll_y = 0
            await until(lambda: window.model_rows.fragments[0].key != before, "older page", tenths=60)
            await asyncio.sleep(0.5)
        fragment = found()
        if fragment is None:
            raise LookupError(f"no tool call in reach draws {wanted}")
        window.toggle_details(fragment.details_link)
        await until(lambda: fragment.shown.details_open, "details open")
        await asyncio.sleep(1.0)
        window.scrollTo(window.model_rows.index(window.model_rows.row_of(fragment.key)), window.ScrollHint.PositionAtTop)
        await asyncio.sleep(1.5)
        self.report("1-open", key=str(fragment.key)[:80], blocks=[type(block).__name__ for block in fragment.line_blocks])


class LinkScenario(Scenario):
    summary = ("open TOAD_DRIVE_THREAD, find the drawn link naming TOAD_DRIVE_LINK on screen, "
               "tap it, and report the tab it opened")

    async def run(self) -> None:
        await self.open_named(os.environ.get("TOAD_DRIVE_THREAD", "opus-personal-model"))
        wanted = os.environ.get("TOAD_DRIVE_LINK", "claude-cloud-pm-run11")
        window = self.page.messages
        viewport = window.viewport()
        point = next((QPoint(x, y) for y in range(0, viewport.height(), 3) for x in range(0, viewport.width(), 3)
                      if wanted in repr(self.decoded(window.anchor_at(QPoint(x, y))))), None)
        if point is None:
            raise LookupError(f"no drawn link names {wanted}")
        self.report("1-before", link=repr(self.decoded(window.anchor_at(point)))[:120], at=(point.x(), point.y()))
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        await until(lambda: any(wanted in tab for tab in self.tabs()), f"tab for {wanted}")
        await asyncio.sleep(2.0)
        self.report("2-opened")

    @staticmethod
    def decoded(href: str):
        return LineLink.from_href(href) if href else None


class HistoryScenario(Scenario):
    summary = ("open #comms; report the rows loaded; scroll to the top until no older page "
               "arrives, reporting each; then return to the end and report that it follows the newest")

    def rows(self) -> dict[str, object]:
        window = self.page.messages
        fragments = window.model_rows.fragments
        history = self.page.message_history
        return dict(rows=len(fragments), pages=len(history.pages),
                    oldest=fragments[0].timestamp if fragments else None,
                    newest=fragments[-1].timestamp if fragments else None,
                    scroll=window.scroll_y, end=window.max_scroll_y, following=window.follows_tail,
                    marked=len(MARKED))

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.expand("#comms")
        comms = await self.channel_row("#comms")
        app.open_row(comms)
        await until(lambda: self.page is not app.workspace_sessions.home
                    and self.page.messages.model_rows.rowCount(), "#comms rows")
        await asyncio.sleep(1.5)
        self.report("1-opened", **self.rows())
        window = self.page.messages
        for step in range(2, 12):
            before = window.model_rows.fragments[0].key
            window.scroll_y = 0
            try:
                await until(lambda: window.model_rows.fragments[0].key != before, "older page", tenths=40)
            except TimeoutError:
                self.report(f"{step}-top-no-older", **self.rows())
                break
            await asyncio.sleep(0.5)
            self.report(f"{step}-older", **self.rows())
        window.scroll_y = window.max_scroll_y
        await asyncio.sleep(1.0)
        window.jump_to_latest()
        await until(lambda: window.follows_tail and window.scroll_y >= window.max_scroll_y - window.END_SLACK,
                    "end", tenths=100)
        await asyncio.sleep(1.0)
        self.report("20-end", **self.rows())


class HeaderRuleScenario(Scenario):
    summary = ("open #comms at phone size; for each message header shown, report where its rule's "
               "pixels start and end against the row width and the title's length; then the "
               "conversation scrollbar Transient: report the viewport width and the bar over the "
               "text while scrolling and gone once still; then Hidden")

    def rule_extent(self, header, width: int) -> tuple[int, int]:
        """The leftmost and rightmost drawn pixel of the header laid out at ``width``."""
        window = self.page.messages
        document = window.rows.header_document(header, window.font(), width)
        image = QImage(width, max(1, int(document.size().height())), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        document.drawContents(painter)
        painter.end()
        drawn = [x for x in range(width) if any(image.pixelColor(x, y).alpha() for y in range(image.height()))]
        return (drawn[0], drawn[-1]) if drawn else (-1, -1)

    def bar(self) -> dict[str, object]:
        window = self.page.messages
        overlay = window.findChild(OverlayScrollBar)
        return dict(viewport=window.viewport().width(), bar_beside=window.verticalScrollBar().width(),
                    overlay=None if overlay is None else (overlay.isVisible(), round(overlay.opacity.opacity(), 2),
                                                          overlay.geometry().getRect()))

    async def run(self) -> None:
        app = self.app
        app.resize(412, 915)
        await self.open_named(os.environ.get("HEADER_TARGET", "#comms"))
        window = self.page.messages
        width = window.viewport().width() - 8
        headers = [fragment.sticky_header(len(fragment.line_blocks) - 1, 1)[-1]
                   for fragment in window.model_rows.fragments
                   if fragment.line_blocks and fragment.sticky_header(len(fragment.line_blocks) - 1, 1)]
        seen: dict[int, tuple] = {}
        for header in headers:
            title = "".join(span.text for span in header.spans)
            seen.setdefault(len(title), (title, *self.rule_extent(header, width)))
        for length, (title, left, right) in sorted(seen.items())[:8]:
            print(f"rule: width={width} title_len={length} left={left} right={right} title={title[:40]!r}",
                  flush=True)
        self.report("1-headers", headers=len(headers), **self.bar())
        app.saved_settings.set(SETTINGS.ui.scrollbar, TransientScrollbar)
        await asyncio.sleep(0.5)
        self.report("2-transient-idle", **self.bar())
        window.scroll_y = max(0, window.scroll_y - window.viewport().height())
        await asyncio.sleep(0.15)
        self.report("3-transient-scrolling", **self.bar())
        await asyncio.sleep(2.0)
        self.report("4-transient-still", **self.bar())
        app.saved_settings.set(SETTINGS.ui.scrollbar, HiddenScrollbar)
        await asyncio.sleep(0.5)
        window.scroll_y = max(0, window.scroll_y - window.viewport().height())
        await asyncio.sleep(0.15)
        self.report("5-hidden-scrolling", **self.bar())


class StickyScenario(Scenario):
    summary = ("open STICKY_TARGET (#comms by default); scroll into the middle of its tallest message "
               "and report the pinned header over the top row, then put that message's header on the "
               "top row and report the pin hidden, as Textual's StickyHeader pins and hides")

    def pinned(self) -> dict[str, object]:
        window = self.page.messages
        pin = window.sticky_header
        top = window.top_page()
        return dict(shown=pin.isVisible(),
                    text=pin.document.toPlainText().strip() if pin.document is not None else "",
                    top=getattr(top, "under", None) and (top.under.block, top.under.row),
                    geometry=(pin.x(), pin.y(), pin.width(), pin.height()))

    async def run(self) -> None:
        self.app.resize(int(os.environ.get("WIDTH", 412)), 915)
        await self.open_named(os.environ.get("STICKY_TARGET", "#comms"))
        window = self.page.messages
        rows = window.model_rows
        headed = [row for row, fragment in enumerate(rows.fragments)
                  if fragment.line_blocks and fragment.sticky_header(len(fragment.line_blocks) - 1, 1)]
        tallest = max(headed, key=lambda row: window.visualRect(rows.index(row, 0)).height())
        fragment = rows.fragments[tallest]
        header = fragment.sticky_header(len(fragment.line_blocks) - 1, 1)[-1]
        words = "".join(span.text for span in header.spans).split()
        rect = window.visualRect(rows.index(tallest, 0))
        window.scroll_y = window.scroll_y + rect.top() + rect.height() // 2
        await asyncio.sleep(0.8)
        facts = self.pinned()
        self.report("1-mid-message", header=" ".join(words), height=rect.height(), **facts)
        assert facts["shown"], "mid-message: no header pinned"
        assert all(word in facts["text"] for word in words), f"pinned {facts['text']!r} is not {words}"
        rect = window.visualRect(rows.index(tallest, 0))
        window.scroll_y = window.scroll_y + rect.top()
        await asyncio.sleep(0.8)
        facts = self.pinned()
        self.report("2-header-on-top", **facts)
        assert not facts["shown"], "the message's own header is on the top row, yet a copy is pinned"


class TallArrivalScenario(StickyScenario):
    summary = ("open TARGET (#scratch) following its end; SENDER (scratch-live-pipeline) posts one "
               "message taller than the window; once the window glides down into it, its header "
               "must be pinned over the top row without the reader scrolling")

    async def run(self) -> None:
        self.app.resize(int(os.environ.get("WIDTH", 412)), 915)
        target = os.environ.get("TARGET", "#scratch")
        sender = os.environ.get("SENDER", "scratch-live-pipeline")
        await self.open_named(target)
        window = self.page.messages
        await until(lambda: window.follows_tail, "following the end")
        stamp = time.strftime("%H:%M:%S")
        body = "\n".join(f"tall arrival {stamp} line {line}" for line in range(120))
        process = await asyncio.create_subprocess_exec(
            "agent-comms", "send", "--from", sender, "--to", target, "--type", "info", "--body", body,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, error = await process.communicate()
        assert process.returncode == 0, error.decode(errors="replace")[-300:]
        await until(lambda: any(f"tall arrival {stamp} line 119" in fragment.clipboard_text
                                for fragment in window.model_rows.fragments), "the tall message's row")
        await until(lambda: window.glide is None and window.follows_tail, "the glide landed on the end")
        await asyncio.sleep(0.5)
        facts = self.pinned()
        self.report("1-tall-arrived", **facts)
        assert facts["shown"], "a tall arrival fills the window, yet its header is not pinned"
        assert sender in facts["text"], f"pinned {facts['text']!r} is not {sender}'s header"


class EscapeScenario(Scenario):
    summary = ("in the scratch-live-pipeline thread, then #comms: scroll off the tail, press Escape in "
               "the composer, and report the view back on its latest row (BackToBottomAction, bound on "
               "every QtConversation)")

    def at_latest(self) -> dict[str, object]:
        window = self.page.messages
        return dict(scroll=window.scroll_y, end=window.max_scroll_y, following=window.follows_tail,
                    jumpable=window.can_jump_to_latest)

    def escape_shortcuts(self) -> list[str]:
        """The live Escape shortcuts this page binds, by the action each answers."""
        return sorted(type(bound.action).__name__ for bound in self.app.action_keys.bound.values()
                      if bound.shortcut.parent() is self.page
                      and any(key.toString() == "Esc" for key in bound.shortcut.keys()))

    async def run(self) -> None:
        self.app.resize(412, 915)
        self.app.show()
        for step, target in enumerate(("#comms", "scratch-live-pipeline"), start=1):
            await self.open_named(target)
            await until(lambda: self.page.composer is not None, f"{target} composer")
            window = self.page.messages
            window.scroll_y = 0
            await until(lambda: window.can_jump_to_latest, f"{target} off the tail", tenths=40)
            self.report(f"{step}a-{target}-scrolled", shortcuts=self.escape_shortcuts(), **self.at_latest())
            assert "BackToBottomAction" in self.escape_shortcuts(), f"{target}: no Escape shortcut bound"
            self.app.activateWindow()
            editor = self.page.composer.editor
            editor.setFocus()
            await asyncio.sleep(0.2)
            QTest.keyClick(editor, Qt.Key.Key_Escape)
            await until(lambda: window.follows_tail and window.scroll_y >= window.max_scroll_y - window.END_SLACK,
                        f"{target} back at its latest row", tenths=60)
            self.report(f"{step}b-{target}-escaped", **self.at_latest())
            # At the tail nothing is off it: Escape falls through to the composer's own
            # `DismissAction`, which clears the unsent draft (Textual's order on a Prompt).
            editor.setFocus()
            editor.insertPlainText("draft kept until Escape")
            await asyncio.sleep(0.2)
            QTest.keyClick(editor, Qt.Key.Key_Escape)
            await until(lambda: editor.toPlainText() == "", f"{target} draft dismissed", tenths=30)
            self.report(f"{step}c-{target}-dismissed", draft=editor.toPlainText(), **self.at_latest())


class WelcomeScenario(Scenario):
    summary = "print the welcome's listings, then open its first row"

    async def run(self) -> None:
        await self.listed()
        welcome = self.app.workspace_sessions.home
        sections = list(welcome.rows.items())
        self.report("1-welcome", **{section.text(0): [section.child(index).key for index in range(section.childCount())]
                                    for section in sections})
        welcome.rows.activate(sections[0].child(0))
        await until(lambda: self.page is not welcome, "opened")
        await asyncio.sleep(1.0)
        self.report("2-opened")


class MenuScenario(Scenario):
    summary = "list the menu's actions and run each one but Quit"

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.menu.click()
        await asyncio.sleep(0.3)
        self.report("1-menu", actions=[row.label.text() for row in app.menu_panel.findChildren(QtMenuRow)])
        app.menu_panel.hide()
        for command, label in ApplicationAction.menu(app):
            if type(command) is QuitAction:
                continue  # it would end the process this drive runs in
            try:
                await command.apply(app)
                await asyncio.sleep(1.5)
                self.report(f"2-{command.declared_name}", action=label)
            except Exception as error:
                print(f"{label}: FAILED {type(error).__name__}: {error}", flush=True)
                traceback.print_exc()
        app.show_warning("this drive's own notice; nothing failed", "Drive")
        await asyncio.sleep(0.3)
        self.report("3-notice", notices=app.float_layer.shown_notices(), shown=app.float_layer.isVisible())


class MenuTextScenario(Scenario):
    summary = ("open the menu at WIDTH (412) and fail when any of its lines is drawn in less height "
               "than its font's full height: the descenders of a description line were cut on the phone")

    async def run(self) -> None:
        from pyqt_reactive.widgets.fitted_text import FittedText
        self.app.resize(int(os.environ.get("WIDTH", 412)), 915)
        await self.listed()
        self.app.menu_panel.input_modality = TouchInput  # the phone's: each description is a second line
        self.app.menu.click()
        await asyncio.sleep(0.5)
        lines = [line for row in self.app.menu_panel.findChildren(QtMenuRow)
                 for line in row.findChildren(FittedText)]
        clipped = [(line.text()[:30], line.contentsRect().height(), line.fontMetrics().height())
                   for line in lines if line.contentsRect().height() < line.fontMetrics().height()]
        if lines:
            line = lines[0]
            button = line.parentWidget()
            print("line geometry:", dict(height=line.height(), contents=line.contentsRect().height(),
                  margins=(line.contentsMargins().top(), line.contentsMargins().bottom()),
                  minimum=line.minimumSizeHint().height(), button=button.height(),
                  button_minimum=button.minimumHeight(), panel_sheet=self.app.menu_panel.styleSheet()[:300],
                  app_sheet_label=[rule[:120] for rule in QApplication.instance().styleSheet().split("}") if "QLabel" in rule][:4]),
                  flush=True)
        self.report("1-menu", lines=len(lines), clipped=clipped[:6])
        assert lines, "the menu shows no lines"
        assert not clipped, f"{len(clipped)} menu lines drawn shorter than their font: {clipped[:3]}"


class FeedbackScenario(Scenario):
    summary = ("the reader's feedback at a Pixel 8a's width: the wait a slow thread open shows in place, "
               "#comms' first page loading, an operation's wait floating over the page, a notice that "
               "floats without moving the history, the menu under touch (no keys, tap-high rows), "
               "then the menu under keys at 790px")

    async def run(self) -> None:
        app = self.app
        app.resize(int(os.environ.get("WIDTH", 412)), 915)
        await self.listed()
        await self.expand("Threads", "#comms")
        # 1. A slow open: the shared reader is held back a second, as a slow bus would hold it.
        reader = app.navigation_reader
        real_read = reader.read

        async def slow_read(request):
            await asyncio.sleep(1.2)
            return await real_read(request)

        reader.read = slow_read
        try:
            await self.found(lambda row: True, "thread row", rows=self.thread_rows)
            threads = self.thread_rows()
            app.open_row(next((row for row in threads if row.target.name == "scratch-live-pipeline"), threads[0]))
            await until(lambda: isinstance(self.page, QtOpeningSessionView), "opening view", tenths=50)
            await asyncio.sleep(0.5)
            opening = self.page
            self.report("1-opening", shown=opening.pending.isVisible(), words=opening.pending.label.text(),
                        sweeping=opening.pending.sweep.working)
            await until(lambda: not isinstance(self.page, QtOpeningSessionView), "opened", tenths=150)
        finally:
            reader.read = real_read
        await asyncio.sleep(1.0)
        self.report("2-opened", waiting=app.float_layer.isVisible())
        # 2. #comms' first page: its wait floats over the history until the first rows are drawn.
        app.open_row(await self.channel_row("#comms"))
        seen: list[tuple[bool, str]] = []
        for _ in range(60):
            await asyncio.sleep(0.05)
            if isinstance(self.page, ConversationView):
                pending = self.page.messages.history.waiting.pending
                seen.append((pending.isVisible(), pending.label.text()))
                if pending.isVisible():
                    self.report("3-first-page", words=pending.label.text())
                    break
        await until(lambda: self.page.messages.model_rows.rowCount(), "#comms rows", tenths=150)
        await asyncio.sleep(1.0)
        history = self.page.messages.history
        self.report("4-first-page-drawn", seen_waiting=any(shown for shown, _ in seen),
                    waiting_now=history.waiting.isVisible())
        # 3. An operation the reader waits on floats its wait over the page.
        app.run_operation(MenuActionRun, lambda: asyncio.sleep(1.2))
        await asyncio.sleep(0.5)
        self.report("5-operation", shown=app.float_layer.isVisible(),
                    words=app.float_layer.pending.label.text())
        await asyncio.sleep(1.2)
        self.report("6-operation-done", shown=app.float_layer.isVisible())
        # 4. A notice floats: the history's first row stays where it was.
        view = self.page.messages

        def first_row_y() -> tuple[int, int, int]:
            """Where the history's viewport sits in the window, its height, and how far it is
            scrolled: a notice in the page's layout would move or shrink it."""
            port = view.viewport()
            return port.mapTo(app, QPoint(0, 0)).y(), port.height(), view.verticalScrollBar().value()

        before = first_row_y()
        app.show_error("drive's forced refusal; nothing failed", "Drive")
        await asyncio.sleep(0.3)
        after = first_row_y()
        self.report("7-notice", notices=app.float_layer.shown_notices(), row_y_before=before,
                    row_y_after=after, moved=before != after)
        if before != after:
            raise AssertionError(f"the notice moved the history: {before} -> {after}")
        app.float_layer.findChild(QtNoticeCard).dismiss()
        await asyncio.sleep(0.3)
        # 5. The menu under touch, then under keys at a desktop width.
        for step, modality, width in (("8-menu-touch", TouchInput, 412), ("9-menu-keys", KeyboardInput, 790)):
            app.resize(width, 915)
            app.menu_panel.input_modality = modality
            app.menu_panel.hide()
            app.menu.click()
            await asyncio.sleep(0.4)
            rows = app.menu_panel.findChildren(QtMenuRow)
            keys = [label.text() for row in rows for label in row.findChildren(QLabel)
                    if "bold" in label.styleSheet()]
            self.report(step, rows=len(rows), keys_shown=keys[:4],
                        least_height=min(row.height() for row in rows) if rows else 0)
            app.menu_panel.hide()


class ShippedScenario(ParticipantSteps):
    summary = ("open every view kind the phone has and press every bound key, failing on any "
               "exception: tools/android/shipped_run.py runs it on the shipped bundle")

    # Menu actions that start an agent or create a thread change the bus; the views they open
    # are the conversation views this scenario opens anyway.
    creates = (NewSessionAction, NewThreadAction, QuitAction)

    def __init__(self, app: QtToadApp, out: Path) -> None:
        super().__init__(app, out)
        self.faults: list[str] = []
        previous = sys.excepthook

        def record(kind, error, trace) -> None:
            # A Qt slot's exception reaches here instead of the awaiting code.
            self.faults.append("".join(traceback.format_exception(kind, error, trace)))
            previous(kind, error, trace)
        sys.excepthook = record

    async def step(self, label: str, run) -> None:
        try:
            await run()
        except Exception:
            self.faults.append(f"{label}:\n{traceback.format_exc()}")
        await asyncio.sleep(0.5)
        self.report(label)

    def close_dialogs(self) -> None:
        for dialog in self.app.findChildren(QDialog):
            if dialog.isVisible():
                dialog.close()

    async def press_bound_keys(self, label: str) -> None:
        """Every key a live shortcut answers, pressed as a real key event with focus in the
        view's composer and again on its history, as a person would press it. Before each
        press the history is off its tail and the composer holds a draft, so the actions
        answering it are available. Qt's focus routing and key competition then decide what
        runs (`ActionKeys.resolve`); each press must run exactly one action and raise nothing."""
        keys = self.app.action_keys
        page = self.page
        self.app.show()
        self.app.activateWindow()
        targets = {"composer": page.composer.editor, "history": page.messages}
        results = []
        for where, target in targets.items():
            answered: dict[str, QKeySequence] = {}
            for bound in tuple(keys.bound.values()):
                parent = bound.shortcut.parent()
                if parent.isVisible() and (parent is target or parent.isAncestorOf(target)):
                    for sequence in bound.shortcut.keys():
                        answered.setdefault(sequence.toString(), sequence)
            for spelling, sequence in sorted(answered.items()):
                # Off the tail where the history is long enough to leave it.
                page.messages.scroll_y = 0
                await asyncio.sleep(0.3)
                page.composer.editor.setPlainText("drafted by the shipped run")
                target.setFocus()
                await asyncio.sleep(0.1)
                if not (target is QApplication.focusWidget() or target.isAncestorOf(QApplication.focusWidget())):
                    self.faults.append(f"{label} {where}: focus did not reach {type(target).__name__}")
                    break
                # What the declared order runs here: the first available answering action,
                # or nothing when none is available.
                expected = [type(bound.action).__name__ for bound in keys.order([sequence])
                            if bound.available()][:1]
                del keys.ran[:]
                combination = sequence[0]
                QTest.keyClick(target, combination.key(), combination.keyboardModifiers())
                await asyncio.sleep(0.3)
                ran = [type(action).__name__ for action in keys.ran]
                results.append(f"{where}:{spelling}->{'+'.join(ran) or 'none available'}")
                if ran != expected:
                    self.faults.append(f"{label} {where}: {spelling} ran {ran or 'nothing'}; "
                                       f"the declared order runs {expected or 'nothing (none available)'}")
        page.composer.editor.clear()
        self.report(label, pressed=results)

    async def run(self) -> None:
        app = self.app
        await self.listed()
        self.report("1-welcome")
        await self.step("1-themes", self.apply_offered_themes)
        for command, label in ApplicationAction.menu(app):
            if isinstance(command, self.creates):
                continue
            await self.step(f"2-menu-{command.declared_name}", lambda command=command: command.apply(app))
            if isinstance(command, SettingsAction):
                for dialog in app.findChildren(QtSettingsScreen):
                    for index in range(dialog.tabs.count()):
                        dialog.tabs.setCurrentIndex(index)
                        await asyncio.sleep(0.3)
                        self.report(f"2-settings-page-{index}", page=dialog.tabs.tabText(index))
            self.close_dialogs()
        await self.step("3-channel", lambda: self.open_named("#comms"))
        await self.press_bound_keys("3-channel-keys")
        await self.noticeless("3-channel-activity", lambda: self.tap_activity("3-channel-activity"))
        await self.step("4-thread", lambda: self.open_named("scratch-live-pipeline"))
        thread = await self.found(lambda row: isinstance(row, ConversationRow)
                                  and row.target.name == "scratch-live-pipeline", "thread scratch-live-pipeline")
        await self.step("4-thread-from-channel", lambda: self.open_named("#comms"))
        await self.noticeless("4-thread-tapped-twice", lambda: self.open_twice(thread))
        await self.step("4-thread-details", self.open_details)
        await self.press_bound_keys("4-thread-keys")
        # The reader keys (ctrl+d, ctrl+u, G) are declared for the vim modes only: press every
        # key again in vim normal mode, as a person choosing that keyboard mode would.
        app.saved_settings.set(SETTINGS.ui.key_mode, KeyMode.member_named("vim_normal"))
        await asyncio.sleep(0.5)
        await self.press_bound_keys("5-thread-vim-keys")
        app.saved_settings.set(SETTINGS.ui.key_mode, KeyMode.member_named("standard"))
        self.close_dialogs()
        if self.faults:
            raise AssertionError(f"{len(self.faults)} fault(s) on the shipped app:\n" + "\n".join(self.faults))

    async def apply_offered_themes(self) -> None:
        """The app started with its saved theme (shipped_run saves one Qt does not offer); then
        every scheme Qt offers is applied in turn through the `ui.theme` effect a start applies.
        A scheme that fails to draw is shown and saved as an error file, which fails the run."""
        settings = self.app.saved_settings
        started = self.app.settings.ui.theme
        if started in offered_schemes(os.environ):
            self.faults.append(f"1-themes: started on {started!r}, which Qt offers; shipped_run saves one it does not")
        applied = []
        for name in offered_schemes(os.environ):
            settings.set(SETTINGS.ui.theme, name)
            await asyncio.sleep(0.05)
            applied.append(name)
        settings.set(SETTINGS.ui.theme, started)
        self.report("1-themes", started=started, applied=applied)

    async def noticeless(self, label: str, run) -> None:
        """A step that must post no warning or error notice."""
        posted = len(self.notices)
        await self.step(label, run)
        self.faults.extend(f"{label}: {failure}" for failure in self.failures_since(posted))

    async def open_details(self) -> None:
        self.page.thread_activity.toggle()
        await asyncio.sleep(0.3)
        self.page.thread_activity.inspect_action.click()
        await asyncio.sleep(1.0)


class MissingChannelDestination(ChannelDestination):
    """A destination its view still shows whose channel Core does not know: its read-only
    check fails before anything leaves, the way a refused send does."""

    def shown(self) -> bool:
        return True


class ComposerScenario(Scenario):
    summary = ("type @ and / in #any without sending, then force a send to the scratch channel "
               "#composer-drive-missing, which Core does not know, so it fails before it leaves: "
               "the drive puts nothing on the bus and writes to no teammate")

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.expand("Threads")
        await self.open(await self.channel_row("#any"), "#any")
        composer = self.page.composer
        self.report("1-any", placeholder=composer.editor.placeholderText(),
                    activity=[line.text() for line in self.page.activity])
        await self.type("@")
        await until(lambda: composer.offers.offers, "mention offers", tenths=100)
        self.report("2-mentions", offers=self.offered(len(composer.offers.offers)))
        composer.offers.accept_current()
        self.report("3-mention-accepted", text=composer.text)
        await self.type("/")
        await until(lambda: composer.offers.offers, "command offers", tenths=300)
        self.report("4-commands", count=len(composer.offers.offers),
                    offers=self.offered(8))
        await self.type("/te")
        self.report("5-commands-te", offers=self.offered(5))
        await self.type("")
        view = self.page
        missing = ChannelConversation(ChannelTarget("#composer-drive-missing"))
        destination = MissingChannelDestination(app.source().root, missing, view)
        app.run_operation(ConversationSubmission,
                          lambda: view.submissions.start_bus(TypedText("this send must fail"), destination).prepare())
        await until(lambda: composer.failure.isVisible(), "failure", tenths=100)
        await asyncio.sleep(0.5)
        self.report("6-failed", failure=composer.failure.text(), draft=composer.text,
                    notices=app.float_layer.shown_notices())


class LiveTurnScenario(Scenario):
    summary = ("open scratch-live-pipeline and feed the shared turn code into its Qt view as an ACP "
               "turn would (input row, a thought, a response streamed in pieces, a failure with its "
               "help, the log link); nothing is sent to the bus")

    def live_rows(self) -> list[tuple[str, str]]:
        rows = self.page.messages.model_rows
        tail = [rows.index(row).data(HistoryRows.FRAGMENT) for row in range(rows.rowCount())]
        return [(type(fragment.events[0]).__name__, fragment.events[0].text)
                for fragment in tail if isinstance(fragment, QtLiveFragment)]

    async def run(self) -> None:
        await self.open_named("scratch-live-pipeline")
        view = self.page
        saved = view.messages.model_rows.rowCount()
        await LocalTurnBinding().present_input(view, "qt live turn probe")
        await view.output.append(ThoughtStream(), "Considering the probe")
        await asyncio.sleep(1.5)  # rows render on the delegate's pool; a frame first shows plain text
        self.report("1-input-and-thought", saved=saved, live=self.live_rows())
        stream = ResponseStream()
        for piece in ("The probe ", "renders ", "as rows."):
            await view.output.append(stream, piece)
        await asyncio.sleep(1.5)
        self.report("2-response-streamed", live=self.live_rows())
        await view.output.finish(ResponseStream)
        await TextAgentFail("Agent stopped", "probe failure details").present(view)
        await UnsupportedResumeAgentFail("Resume refused").present(view)
        await asyncio.sleep(1.5)
        self.report("3-failure-and-help", live=self.live_rows(),
                    flash=view.feedback.text() if view.feedback.isVisible() else "")
        view.messages.committed_pages_changed()
        self.report("4-saved-rows-arrived", live=self.live_rows(),
                    rows=view.messages.model_rows.rowCount())


class AgentSessionScenario(Scenario):
    summary = ("over --comms-root, start an agent session on the tests' scripted ACP peer (no "
               "model), send it support.agents.FULL_TURN (the TUI's test_full_agent_turn), answer "
               "its permission question, and read its reply, thought, tool call and terminal "
               "output as live rows; run it on a scratch root, never a live one")

    def live_rows(self) -> list[tuple[str, str]]:
        rows = self.page.messages.model_rows
        tail = [rows.index(row).data(HistoryRows.FRAGMENT) for row in range(rows.rowCount())]
        # A live row's position is negative (`QtLiveBlock`); the text is what the row draws.
        return [(type(fragment.events[0]).__name__,
                 " / ".join(block.selection_text for block in fragment.line_blocks))
                for fragment in tail if fragment is not None and fragment.events
                and fragment.events[0].position < 0]

    def shown(self, marker: str) -> bool:
        """The marker in a row the agent's turn drew: the prompt's own row names them all."""
        return any(marker in text for kind, text in self.live_rows() if kind != "UserTranscript")

    async def run(self) -> None:
        sys.path.insert(0, str(PROJECT / "tests"))
        from support.agents import FULL_TURN, peer, script
        from toad.launch_binding import AgentAttached
        from toad.qt.acp_tab import QtAcpSessionView

        project = self.out / "project"
        project.mkdir(exist_ok=True)
        app = self.app
        await app.session_navigation.start_agent_session(AgentAttached(peer("scripted")), Checkout(project))
        await until(lambda: isinstance(self.page, QtAcpSessionView), "agent session tab")
        view = self.page
        await until(lambda: view.agent_binding.ready, "agent ready", tenths=600)
        await until(lambda: view.composer is not None, "composer")
        self.report("1-agent-ready", agent=view.agent_binding.get_info(),
                    identity=view.identity_line.text())
        await self.type(script(*FULL_TURN))
        view.composer.send()
        await until(lambda: self.shown("TURN_TOOL"), "reply, thought and tool call", tenths=300)
        await until(lambda: view.question.isVisible(), "permission question", tenths=300)
        self.report("2-permission-asked", live=self.live_rows(), question=view.question._title.text())
        allow = next(button for button in view.question.findChildren(QPushButton) if button.text() == "Allow")
        allow.click()
        await until(lambda: self.shown("TURN_TERMINAL_OUTPUT"), "terminal output", tenths=300)
        await until(lambda: self.shown("TURN_DONE") and not view.turns.owner.busy, "turn finished", tenths=300)
        await asyncio.sleep(1.0)
        self.report("3-turn-over", live=self.live_rows(),
                    question_visible=view.question.isVisible(),
                    busy=view.turns.owner.busy)


class CommandScenario(Scenario):
    summary = ("run /copy in #any through the shared command catalog, then a refused /copy, "
               "then open #comms' /rename-tag form, fill it and cancel it: nothing is applied, "
               "sent or marked read on the bus, and no teammate's DM is opened")

    form_name: ClassVar[str] = "qt-drive-never-applied"

    def forms(self) -> list[QtCommandDialog]:
        return [form for form in self.app.findChildren(QtCommandDialog) if form.isVisible()]

    async def send(self, text: str) -> None:
        await self.type(text)
        self.page.composer.send()
        await asyncio.sleep(0.5)

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.expand("Threads")
        await self.open(await self.channel_row("#any"), "#any")
        composer = self.page.composer
        await self.type("/")
        await until(lambda: composer.offers.offers, "command offers", tenths=300)
        self.report("1-offers", offers=self.offered(20))
        QApplication.clipboard().clear()
        await self.send("/copy")
        await until(lambda: QApplication.clipboard().text() == "#any", "copied", tenths=100)
        self.report("2-copied", clipboard=QApplication.clipboard().text(), draft=composer.text,
                    sending=composer.submitting.text())
        await self.send("/copy now")
        await until(lambda: any("current target" in notice for notice in app.float_layer.shown_notices()),
                    "refused", tenths=100)
        self.report("3-refused", notices=app.float_layer.shown_notices(), shown=app.float_layer.isVisible())
        await self.open(await self.channel_row("#comms"), "#comms")
        await self.send("/rename-tag")
        await until(self.forms, "form", tenths=150)
        form = self.forms()[0]
        dialog = form.dialog
        await until(lambda: not form.preparing(), "choices", tenths=150)
        rows = [(row.label.text(), type(row.editor).__name__) for row in form.form.values.values()]
        self.report("4-form", title=dialog.windowTitle(), rows=rows, confirmation=form.confirmation_text.text(),
                    width=form.minimumSizeHint().width())
        dialog.grab().save(str(self.out / f"{type(self).declared_name}-4-form.png"))
        editor = form.form.editor(DottedFieldPath("new_name"))
        editor.setText(self.form_name)
        form.form.finish()
        await asyncio.sleep(1.0)
        self.report("5-filled", value=form.arguments(), confirmation=form.confirmation_text.text(),
                    confirmable=form.confirmed.isVisible(), notices=app.float_layer.shown_notices())
        dialog.grab().save(str(self.out / f"{type(self).declared_name}-5-filled.png"))
        dialog.reject()
        answer = await form.answer
        await asyncio.sleep(0.5)
        self.report("6-cancelled", answer=answer, open_forms=len(self.forms()))


class PhoneScenario(Scenario):
    summary = "list every widget too wide for a Pixel 8a, on the welcome and with the sidebar up"

    width: ClassVar[int] = 412  # the Pixel 8a's 1080 px at its 2.625 device pixel ratio

    def too_wide(self) -> list[str]:
        """Each visible widget whose layout cannot go narrower than the phone, widest first."""
        widgets = [self.app, *self.app.findChildren(QWidget)]
        wide = [(widget.minimumSizeHint().width(), widget) for widget in widgets
                if widget.isVisible() and widget.minimumSizeHint().width() > self.width]
        return [f"{width} {type(widget).__name__} {widget.objectName() or widget.parent().__class__.__name__}"
                for width, widget in sorted(wide, key=lambda pair: -pair[0])]

    async def run(self) -> None:
        await self.listed()
        self.app.resize(self.width, 915)
        await asyncio.sleep(0.5)
        self.report("1-welcome", window=self.app.width(), too_wide=self.too_wide())
        # Android's style lays pages out with wider margins than desktop; a widget sized
        # from its page's width grows the page by the difference on every resize.
        self.app.workspace_sessions.home.layout().setContentsMargins(20, 20, 20, 20)
        widths = []
        for _ in range(4):
            self.app.resize(self.width, 915)
            await asyncio.sleep(0.3)
            widths.append(self.app.width())
        self.report("1b-android-margins", widths=widths, too_wide=self.too_wide())
        await self.app.reveal_sidebar()
        await asyncio.sleep(0.5)
        self.report("2-sidebar", window=self.app.width(), too_wide=self.too_wide())


MARKED: list = []


async def record_mark(buffer: WirePageBuffer, page) -> None:
    """The drive's reader is not the profile's owner: what the shared read marking would
    acknowledge is recorded, and nothing is marked read on the bus."""
    MARKED.append(page)


class PersistScenario(Scenario):
    """First half of a close/open check: open a thread and a channel, move the channels bar,
    then end as the app ends. `restored`, run next in a fresh process over the same
    XDG_STATE_HOME/XDG_CONFIG_HOME, reads back what came back."""

    summary = "open the first listed thread and #comms, move the channels bar to the bottom, then quit"

    async def run(self) -> None:
        app = self.app
        await self.listed()
        await self.expand("#any")
        await self.open(await self.found(lambda row: True, "thread row", rows=self.thread_rows), "first thread")
        await self.open_named("#comms")
        app.show_sidebar()
        await asyncio.sleep(0.5)
        next(control for control in app.channels_side._actions
             if isinstance(control.action, DirectionalSidebarPlacementAction)
             and control.action.direction is BottomSidebarEdge).click()
        await asyncio.sleep(0.5)
        app.hide_sidebar()
        await asyncio.sleep(0.5)
        placed = app.sidebar_layout.get(ChannelsSidebarPlacement)
        from toad.preferences import SavedSettings
        self.report("1-before-close", selected=app.tabs.tabText(app.tabs.currentIndex()),
                    settings_file=SavedSettings.path().is_file(), unsaved=app.saved_settings.unsaved,
                    channels_bar=placed.side.declared_name, roster=[i.mode_name for i in app.tab_order.names])


class BarSaveScenario(Scenario):
    """A moved bar is in the settings file before any background or quit."""

    summary = "move the channels bar to the bottom; report whether toad.json holds it at once"

    async def run(self) -> None:
        from toad.preferences import SavedSettings
        app = self.app
        app.show_sidebar()
        await asyncio.sleep(0.5)
        next(control for control in app.channels_side._actions
             if isinstance(control.action, DirectionalSidebarPlacementAction)
             and control.action.direction is BottomSidebarEdge).click()
        await asyncio.sleep(1.0)
        path = SavedSettings.path()
        self.report("1-moved", path=str(path), settings_file=path.is_file(), unsaved=app.saved_settings.unsaved,
                    holds_bottom=path.is_file() and '"bottom"' in path.read_text())


class RestoredScenario(Scenario):
    """Second half: what a fresh start over the saved state shows before anything is touched."""

    summary = "report the tabs, selection and channels-bar placement a fresh start restored"

    async def run(self) -> None:
        app = self.app
        await self.listed()
        await asyncio.sleep(3.0)
        placed = app.sidebar_layout.get(ChannelsSidebarPlacement)
        self.report("1-after-open", selected=app.tabs.tabText(app.tabs.currentIndex()),
                    channels_bar=placed.side.declared_name, roster=[i.mode_name for i in app.tab_order.names])
        # Cold start, home in front: one real tap on the restored thread's sidebar row opens
        # its tab (the restored entry's view is built on this first selection).
        restored_thread = next((identity for identity in app.tab_order.names
                                if identity.mode_name.startswith("mailbox-")), None)
        if restored_thread is not None:
            await app.select_session(app.tab_order.home)
            app.show_sidebar()
            await self.expand("#any")
            row = await self.listed_thread(restored_thread.key.name)
            tree = row.treeWidget()
            tree.scrollToItem(row)
            await asyncio.sleep(0.5)
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             tree.visualItemRect(row).center())
            await asyncio.sleep(3.0)
            self.report("2-first-tap", tapped=restored_thread.key.name, view=type(self.page).__name__)
        # A restored tab builds its view when it is first selected: select each, as a tap does.
        for index in range(app.tabs.count()):
            app.visit_index(index)
            await asyncio.sleep(2.0)
            self.report(f"3-tab-{index}", view=type(self.page).__name__,
                        rows=getattr(getattr(self.page, "messages", None), "model_rows", None) and
                        self.page.messages.model_rows.rowCount())


class PlacementScenario(Scenario):
    summary = ("move and float the channels bar, then change the view settings for #comms and "
               "a DM through the thread bar; list anything too wide for a Pixel 8a")

    width: ClassVar[int] = 412

    def too_wide(self) -> list[str]:
        widgets = [self.app, *self.app.findChildren(QWidget)]
        wide = [(widget.minimumSizeHint().width(), widget) for widget in widgets
                if widget.isVisible() and widget.minimumSizeHint().width() > self.width]
        return [f"{width} {type(widget).__name__}" for width, widget in sorted(wide, key=lambda pair: -pair[0])]

    def where(self, side) -> str:
        """Where the side sits in the chrome, and whether its pane shows."""
        if side.isHidden():
            return "absent"
        box = side.geometry()
        return (f"{box.x()},{box.y()} {box.width()}x{box.height()} "
                f"{'folded' if side.collapsed else 'open'}")

    def placement(self, identity) -> str:
        placed = self.app.sidebar_layout.get(identity)
        return placed.side.declared_name + ("/float" if placed.floating else "")

    def move_control(self, pane, edge: type[SidebarEdge]) -> QtSidebarAction:
        return next(control for control in pane._actions
                    if isinstance(control.action, DirectionalSidebarPlacementAction)
                    and control.action.direction is edge)

    def float_control(self, pane) -> QtSidebarAction:
        return next(control for control in pane._actions
                    if isinstance(control.action, FloatSidebarPlacementAction))

    async def settle(self) -> None:
        await asyncio.sleep(0.5)

    async def opened(self, before) -> None:
        home = self.app.workspace_sessions.home
        await until(lambda: self.page is not before and self.page is not home, "conversation")
        await self.settle()

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        await self.settle()
        await self.expand("#comms", "Threads")
        comms = await self.channel_row("#comms")
        home = app.workspace_sessions.home
        app.open_row(comms)
        await self.opened(home)
        pane = app.channels_side
        # The strip is only the edge's toggle text; the move arrows and Float live in the
        # content, as the Textual sidebar draws them. Prove the structure from the widget tree.
        self.report("1-structure",
                    channels_bar=pane.toggle.text().replace("\n", ""),
                    pane_actions=[control.action.name for control in pane._actions],
                    thread_bar=app.thread_side.toggle.text().replace("\n", ""),
                    too_wide=self.too_wide())
        # Open the channels pane, then move it top, bottom and float it from the pane's own
        # controls: each relocates the one pane over the shared SidebarLayout.
        app.show_sidebar()
        await self.settle()
        self.report("2-shown", placement=self.placement(ChannelsSidebarPlacement), at=self.where(pane))
        self.move_control(pane, TopSidebarEdge).click()
        await self.settle()
        self.report("3-move-top", placement=self.placement(ChannelsSidebarPlacement), at=self.where(pane))
        self.move_control(pane, BottomSidebarEdge).click()
        await self.settle()
        self.report("4-move-bottom", placement=self.placement(ChannelsSidebarPlacement), at=self.where(pane))
        self.float_control(pane).click()
        await self.settle()
        self.report("5-float", placement=self.placement(ChannelsSidebarPlacement),
                    at=self.where(pane), float_label=self.float_control(pane).text(), too_wide=self.too_wide())
        self.float_control(pane).click()
        app.hide_sidebar()
        await self.settle()
        # The thread bar opens the open conversation's view settings. Toggle one category and
        # read it back off the view: the pane writes the view's own selection, no second copy.
        comms_view = app.workspace_sessions.selected
        category = next(iter(MessageCategory.members_with(MessageCategory)))
        app.thread_side.toggle_pane()
        await self.settle()
        before = len(set(comms_view.visible_categories))
        app.thread_pane._comms_panel._checks[category].click()
        await self.settle()
        comms_after = set(comms_view.visible_categories)
        self.report("6-comms-settings", toggled=category.label, where=self.where(app.thread_side),
                    categories=[control.text() for control in app.thread_pane._comms_panel._checks.values()],
                    before_shown=before, after_shown=len(comms_after),
                    category_shown=(category in comms_after), too_wide=self.too_wide())
        # A DM: its own bar heading and its own, independent view settings. The
        # sidebar may have re-rendered after the pane toggles, so re-fetch the
        # peer row from the current tree instead of reusing the stale handle.
        peer = await self.thread_row()
        app.open_row(peer)
        await self.opened(comms_view)
        dm_view = app.workspace_sessions.selected
        self.report("7-dm-open", thread_heading=app.thread_side.toggle.text().replace("\n", ""),
                    dm_shown=len(set(dm_view.visible_categories)))
        app.thread_pane._comms_panel._checks[category].click()
        await self.settle()
        self.report("8-dm-settings", toggled=category.label,
                    dm_category_shown=(category in dm_view.visible_categories),
                    comms_still=(category in comms_after), where=self.where(app.thread_side),
                    too_wide=self.too_wide())


class SlideScenario(Scenario):
    summary = ("the channels pane's grips at a Pixel 8a's width: drag the resize handle to the wall "
               "and let go (folds, keeps its extent), click the strip (reopens there), drag the folded "
               "strip outward (opens as far as the pointer), take the slider to 0 (folds), then open "
               "and close tabs; prints sizes and the animation's frame gaps")

    width: ClassVar[int] = 412

    @staticmethod
    def press(widget: QWidget, kind: QEvent.Type, at: QPoint, held: bool, screen: QPoint | None = None) -> None:
        """A mouse event at ``at`` in ``widget``, at ``screen`` on the screen: a finger's place on
        the screen does not move when the widget under it does."""
        event = QMouseEvent(kind, QPointF(at), QPointF(screen or widget.mapToGlobal(at)),
                            Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)

    async def drag(self, widget: QWidget, start: QPoint, stop: QPoint, *, steps: int = 12,
                   midway=None) -> None:
        origin = widget.mapToGlobal(start)
        self.press(widget, QEvent.Type.MouseButtonPress, start, True, origin)
        for step in range(1, steps + 1):
            travel = (stop - start) * step / steps
            self.press(widget, QEvent.Type.MouseMove, start + travel, True, origin + travel)
            await asyncio.sleep(0.01)
            if midway is not None and step == steps // 2:
                midway()
        self.press(widget, QEvent.Type.MouseButtonRelease, stop, False, origin + (stop - start))

    def click(self, widget: QWidget) -> None:
        middle = widget.rect().center()
        self.press(widget, QEvent.Type.MouseButtonPress, middle, True)
        self.press(widget, QEvent.Type.MouseButtonRelease, middle, False)

    def wall(self, pane, widget: QWidget, length: int) -> QPoint:
        """``length`` pixels from ``widget``'s middle toward the pane's wall."""
        side = pane.placement.side
        horizontal = side.coordinate(Offset(1, 0)) != 0
        toward = -side.sign * length
        return widget.rect().center() + (QPoint(toward, 0) if horizontal else QPoint(0, toward))

    def state(self, pane) -> str:
        box = pane.geometry()
        return (f"{'folded' if pane.collapsed else 'open'} extent={pane.placement.extent_percent}% "
                f"at={box.x()},{box.y()} {box.width()}x{box.height()}")

    async def landed(self) -> None:
        await until(lambda: not self.app.chrome.slides, "slide landed")
        await asyncio.sleep(0.05)

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        app.show_sidebar()
        await asyncio.sleep(0.6)
        await self.landed()
        pane = app.channels_side
        app.sidebar_layout.resize(ChannelsSidebarPlacement, 40)
        app.rearrange_sidebars()
        await asyncio.sleep(0.3)
        before = pane.placement.extent_percent
        self.report("1-open", pane=self.state(pane))
        stamps: list[float] = []
        moving = PaneSlide.apply_amount

        def timed(slide, amount):
            stamps.append(time.perf_counter())
            moving(slide, amount)
        PaneSlide.apply_amount = timed

        seen: dict[str, str] = {}
        await self.drag(pane.handle, pane.handle.rect().center(), self.wall(pane, pane.handle, pane.width() + 20),
                        midway=lambda: seen.setdefault("mid", self.state(pane)))
        print("  mid-drag:", seen["mid"], flush=True)
        await self.landed()
        assert pane.collapsed and pane.placement.extent_percent == before, self.state(pane)
        self.report("2-dragged-to-wall", pane=self.state(pane))
        stamps.clear()
        self.click(pane.toggle)
        await self.landed()
        assert not pane.collapsed and pane.placement.extent_percent == before, self.state(pane)
        gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:])]
        self.report("3-strip-clicked", pane=self.state(pane))
        self.click(pane.toggle)
        await self.landed()
        assert pane.collapsed, self.state(pane)
        horizontal = pane.placement.side.coordinate(Offset(1, 0)) != 0
        reach = (app.chrome.width() if horizontal else app.chrome.height()) * 30 // 100
        await self.drag(pane.toggle, pane.toggle.rect().center(), self.wall(pane, pane.toggle, -reach))
        await self.landed()
        assert not pane.collapsed, self.state(pane)
        self.report("4-strip-dragged-open", pane=self.state(pane))
        dragged = pane.placement.extent_percent
        self.click(pane.handle)
        await asyncio.sleep(0.2)
        slider = pane.slider
        far = QPoint(slider.width() - 2 if slider.reversed else 1, slider.height() // 2)
        await self.drag(slider, slider.rect().center(), far)
        await self.landed()
        assert pane.collapsed and pane.placement.extent_percent == dragged, self.state(pane)
        self.report("5-slider-to-0", pane=self.state(pane))
        PaneSlide.apply_amount = moving
        print("  opening slide frame gaps ms:", [round(gap * 1000, 1) for gap in gaps],
              "max", round(max(gaps, default=0) * 1000, 1), flush=True)
        await self.expand("#comms")
        comms = await self.channel_row("#comms")
        app.open_row(comms)
        await until(lambda: app.tabs.count() == 1, "#comms tab")
        await asyncio.sleep(0.5)
        grew: list[int] = []
        growing = TabGrowth.apply_amount

        started: list[float] = []
        starting = TabGrowth.start_transition

        def began(growth, clock, effect):
            started.append(time.perf_counter())
            starting(growth, clock, effect)
        TabGrowth.start_transition = began

        def widened(growth, amount):
            growing(growth, amount)
            grew.append(app.tabs.tabRect(app.tabs.count() - 1).width())
            started.append(time.perf_counter())
        TabGrowth.apply_amount = widened
        app.open_row(await self.thread_row())
        await until(lambda: app.tabs.count() == 2, "second tab")
        await until(lambda: not app.tabs.growing, "tab grown", tenths=50)
        TabGrowth.apply_amount = growing
        TabGrowth.start_transition = starting
        print("  tab opening: ms from start to each frame",
              [round((stamp - started[0]) * 1000) for stamp in started[1:]], flush=True)
        settled = app.tabs.tabRect(app.tabs.count() - 1).width()
        print("  tab opening: new tab widths per frame", grew, "settled", settled, flush=True)
        assert len(grew) > 1 and grew[0] < settled, (grew, settled)
        self.report("6-tabs-open")
        ghosts: list[int] = []
        shrinking = TabGhost.apply_amount

        def shrank(ghost, amount):
            shrinking(ghost, amount)
            ghosts.append(ghost.picture.width())
        TabGhost.apply_amount = shrank
        app.close_index(app.tabs.currentIndex())
        await until(lambda: app.tabs.count() == 1, "close")
        await until(lambda: not [label for label in app.tabs.findChildren(QLabel) if label.isVisible()],
                    "ghost gone", tenths=50)
        TabGhost.apply_amount = shrinking
        left = [label for label in app.tabs.findChildren(QLabel) if label.isVisible()]
        print("  tab closing: ghost widths per frame", ghosts, "left after", len(left), flush=True)
        assert len(ghosts) > 1 and ghosts[-1] < ghosts[0] and not left, (ghosts, left)
        self.report("7-tab-closed")


class DragSpeedScenario(Scenario):
    summary = ("open #comms at a Pixel 8a's width, then drag the channels pane's resize handle "
               "40 moves out and back; print each move's handling time and the event loop's time "
               "to settle after it, and the hottest functions (TOAD_DRAG_PROFILE=1)")

    width: ClassVar[int] = 412

    @staticmethod
    def move(widget: QWidget, kind: QEvent.Type, at: QPoint, screen: QPoint, held: bool) -> None:
        QApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(at), QPointF(screen), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        await self.open_named("#comms")
        app.show_sidebar()
        await asyncio.sleep(1.0)
        pane = app.channels_side
        handle = pane.handle
        start = handle.rect().center()
        origin = handle.mapToGlobal(start)
        horizontal = pane.placement.side.coordinate(Offset(1, 0)) != 0
        step = QPoint(4, 0) if horizontal else QPoint(0, 4)
        sign = pane.placement.side.sign
        path = [step * (sign * index) for index in range(1, 21)]
        path += list(reversed(path[:-1])) + [QPoint(0, 0)]
        profile = None
        if os.environ.get("TOAD_DRAG_PROFILE"):
            import cProfile
            profile = cProfile.Profile()
        handled: list[float] = []
        late: list[float] = []
        self.move(handle, QEvent.Type.MouseButtonPress, start, origin, True)
        if profile is not None:
            profile.enable()
        for travel in path:
            began = time.perf_counter()
            self.move(handle, QEvent.Type.MouseMove, start + travel, origin + travel, True)
            handled.append(time.perf_counter() - began)
            # One frame for the loop to draw the move and run what it started; how late the
            # loop gives control back is what a finger feels as lag.
            frame = time.perf_counter()
            await asyncio.sleep(0.016)
            late.append(time.perf_counter() - frame - 0.016)
        released = time.perf_counter()
        self.move(handle, QEvent.Type.MouseButtonRelease, start, origin, False)
        release = time.perf_counter() - released
        await asyncio.sleep(0.3)
        if profile is not None:
            profile.disable()

        def summary(samples: list[float]) -> str:
            ordered = sorted(samples)
            ms = [value * 1000 for value in ordered]
            return (f"median {ms[len(ms) // 2]:.1f} ms, p95 {ms[int(len(ms) * 0.95) - 1]:.1f} ms, "
                    f"max {ms[-1]:.1f} ms over {len(ms)} moves")
        print("  move handled:", summary(handled), flush=True)
        print("  loop late after a move:", summary(late), flush=True)
        print(f"  release: {release * 1000:.1f} ms", flush=True)
        if profile is not None:
            import pstats
            stats = pstats.Stats(profile)
            stats.sort_stats("cumulative").print_stats(40)
        self.report("1-dragged", pane=f"{pane.placement.extent_percent}%")


class ChromeScenario(Scenario):
    summary = ("the sidebar and tab chrome at a Pixel 8a's width: the channels pane open beside "
               "the welcome, then #comms and one of its threads open; print each surface's geometry")

    width: ClassVar[int] = 412
    height: ClassVar[int] = 915

    def geometry(self) -> dict[str, object]:
        """Where each chrome surface sits in window pixels, so the TUI's column split can be
        read against it: the channels pane, both bars, and the conversation page."""
        app = self.app
        def box(widget: QWidget) -> str:
            if not widget.isVisible():
                return "hidden"
            corner = widget.mapTo(app, widget.rect().topLeft())
            return f"{corner.x()},{corner.y()} {widget.width()}x{widget.height()}"
        return dict(channels=box(app.channels_side), channels_strip=box(app.channels_side.toggle),
                    thread=box(app.thread_side), pages=box(app.workspace_sessions.pages),
                    cells=app.chrome.cells(), tabs=box(app.tabs))

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, self.height)
        await asyncio.sleep(0.5)
        app.show_sidebar()
        await self.channel_row("#comms")
        await self.expand("#comms")
        self.report("1-welcome", **self.geometry())
        comms = await self.channel_row("#comms")
        home = app.workspace_sessions.home
        app.open_row(comms)
        await until(lambda: self.page is not home and self.page.content_ready.is_set(), "#comms")
        await asyncio.sleep(1.5)
        self.report("2-channel", **self.geometry())
        # The tab's own message-style override redraws its messages at once, as the TUI's.
        channel = self.page
        style = lambda: type(channel.message_history.page_source.loader.style).__name__
        before_style = style()
        # The override is the view's on the live bus: edit to the style the tab does not draw
        # now, and reset it after, so no run inherits the last run's override (a fixed target
        # made every run after the first a no-op that timed out).
        override = channel.configuration_state.field("ui.message_style")
        override.edit(IrcMessageStyle if before_style == MarkdownMessageStyle.__name__ else MarkdownMessageStyle)
        await until(lambda: style() != before_style, "message style", tenths=100)
        await asyncio.sleep(1.0)
        self.report("2b-channel-style", before=before_style, after=style())
        override.reset()
        # Step 7 reads the thread's configure form, which Core offers only a live native owner.
        native = await self.live_native_thread_rows()
        peer = native[0] if native else await self.thread_row()
        before = self.page
        app.open_row(peer)
        await until(lambda: self.page is not before, "thread")
        await asyncio.sleep(1.5)
        self.report("3-thread", peer=peer.key, **self.geometry())
        app.thread_side.toggle_pane()
        await asyncio.sleep(1.0)
        picker = app.thread_pane.menu.picker
        entries = [picker.itemText(index) for index in range(picker.count())]
        self.report("4-thread-pane", entries=entries, **self.geometry())
        # The Comms page, then the first of the view's own settings: each page the shared
        # entries list, picked as Textual's PanelPicker picks it.
        picker.setCurrentIndex(entries.index("Comms"))
        await asyncio.sleep(1.5)
        self.report("5-comms-page", shown=picker.currentText())
        settings = len(panel_specs_for_view(is_session=True))
        picker.setCurrentIndex(settings)
        await asyncio.sleep(0.5)
        self.report("6-settings-page", shown=picker.currentText())
        # The view's configuration operations load after its settings, as Textual's picker
        # adds them: the last entry is the thread's next-turn model form, an embedded page.
        if native:
            roster = len(panel_specs_for_view(is_session=True)) + len(tuple(self.page.configuration_fields()))
            await until(lambda: picker.count() > roster, "configuration actions", tenths=150)
            picker.setCurrentIndex(picker.count() - 1)
            await asyncio.sleep(1.0)
            self.report("7-action-page", entries=picker.count(), shown=picker.currentText())
        else:
            self.report("7-action-page", skipped="the bus lists no thread with a running native owner "
                        "(each is an external CLI's, bus-held, or its owner is not running), so none "
                        "is offered the configure form")
        # A per-view override repaints the view at once: the column narrows to 40 cells and
        # centres, and the info bar hides; both read through the view's own settings.
        # With the settings pane closed the conversation has room for a 40-cell column.
        app.thread_side.toggle_pane()
        await asyncio.sleep(0.5)
        view = self.page
        state = view.configuration_state
        margins = lambda: (view.layout().contentsMargins().left(), view.layout().contentsMargins().right())
        overrides = {"ui.column": True, "ui.column_width": 40,
                     "ui.column_alignment": CenterColumnAlignment, "ui.info_bar": False}
        before = margins()
        for path, value in overrides.items():
            state.field(path).edit(value)
        await asyncio.sleep(0.5)
        self.report("8-view-override", width=view.width(), cell=view.fontMetrics().averageCharWidth(),
                    margins_before=before, margins_after=margins(),
                    info_bar=view.composer.info_bar.isVisible())
        # These overrides are the view's on the live bus: reset them, so the next run starts
        # from the inherited layout and its before/after shows the repaint again.
        for path in overrides:
            state.field(path).reset()


class Chrome110Scenario(ChromeScenario):
    summary = "the chrome scenario at 110 font cells across, a terminal's common width"

    width: ClassVar[int] = 790
    height: ClassVar[int] = 900


class WideScenario(ChromeScenario):
    summary = "the chrome scenario at a desktop window's width"

    width: ClassVar[int] = 1400
    height: ClassVar[int] = 900


class WaveScenario(Scenario):
    summary = ("the name wave on the sidebar's thread lines: one line forced to wave with the "
               "shared clock frozen at three instants (the band's characters at each, for "
               "the TUI's at the same width: TOAD_WAVE_CELLS), then the live working threads")

    width: ClassVar[int] = 412
    instants: ClassVar[tuple[float, ...]] = (1000.0, 1000.35, 1000.7)

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        app.show_sidebar()
        await asyncio.sleep(1.0)
        tree = app.sidebar
        name = os.environ.get("TOAD_WAVE_THREAD")
        row = await self.thread_row() if not name else await self.found(
            lambda line: isinstance(line, ConversationRow) and line.key == name, f"thread {name}")
        tree.scrollToItem(row)
        await asyncio.sleep(0.5)
        cells = int(os.environ.get("TOAD_WAVE_CELLS", "0"))
        cell = tree.fontMetrics().averageCharWidth()
        if cells:
            # The tree as wide as the TUI's row, so the band covers the same characters.
            tree.setFixedWidth(tree.width() + (cells - tree.line_width(row) // cell) * cell)
            await asyncio.sleep(0.5)
        clock = app.animation_clock
        live_now = clock.now
        row.follow_activity(True)
        delegate = tree.itemDelegateForColumn(0)
        for step, instant in enumerate(self.instants, 1):
            clock.now = lambda instant=instant: instant
            clock.time = instant
            tree.viewport().update()
            await asyncio.sleep(0.2)
            title = row.drawn[1]
            prefix, _ = row.first_line()
            text = prefix + title
            start, end = row.wave_span()
            option = QStyleOptionViewItem()
            layout = delegate._prepared_text(option, tree.indexFromItem(row)).paragraphs[0]
            self.report(f"{step}-frozen", instant=instant, cells=tree.line_width(row) // cell,
                        band=(start, end), chars=text[start:end], bold=layout.font().bold())
        clock.now = live_now
        row.follow_activity(row.busy)
        await asyncio.sleep(1.0)
        waving = [line for line in self.rows(tree.items()) if line.wave_span() is not None]
        if waving:
            tree.scrollToItem(waving[0])
            await asyncio.sleep(0.5)
        self.report("4-live", working=sorted({line.key for line in waving}))
        if waving:
            # A working thread's tab title waves too, as Textual's `SessionLabel` does.
            home = app.workspace_sessions.home
            app.open_row(waving[0])
            await until(lambda: self.page is not home, "working thread")
            await asyncio.sleep(2.0)
            self.report("5-tab", waving_tabs=[mode for mode, wave in app.tabs.waves.items()
                                              if wave.wave_running()])


class ArrivalScenario(Scenario):
    summary = ("open TARGET (#scratch, or a scratch thread such as scratch-live-pipeline), send 3 "
               "messages from the composer while a scratch sender (SENDER) posts 3 into it; log every "
               "row-model update (keys and "
               "message text added and removed) and sample the composer's queue rows every 16 ms; "
               "report a message that leaves the rows and comes back, or a reflow of the queue rows")

    width: ClassVar[int] = 412

    @staticmethod
    def label(fragment) -> str:
        """What a reader sees of the row, and which row it is: a message whose row is replaced
        under a new key shows up as its text leaving and coming back."""
        text = " ".join(fragment.clipboard_text.split())[:48]
        return f"{text} #{hash(fragment.key) & 0xffff:04x}"

    async def run(self) -> None:
        from toad.qt.history import HistoryRows
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        target = os.environ.get("TARGET", "#scratch")
        if target.startswith("#"):
            await self.channel_row(target)
            await self.expand(target)
            app.open_row(await self.channel_row(target))
        else:
            app.open_row(await self.listed_thread(target))
        for tick in range(120):
            page = self.page
            rows = page.messages.model_rows.rowCount() if hasattr(page, "messages") else None
            if tick % 4 == 0:
                print(f"opening t={tick / 2:.1f}s page={type(page).__name__} rows={rows}", flush=True)
            if rows:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(2.0)
        view = self.page
        rows: list[str] = []
        updates: list[tuple[float, tuple, tuple]] = []
        started = time.monotonic()
        original = HistoryRows.show

        first_shown: dict[str, float] = {}  # a row's full text, when it first showed
        # When Core's revisions reach this app: the pace a burst can show at, at best.
        from toad.client.connection import CoordinationAccess
        revisions: list[float] = []
        observed = CoordinationAccess.revision_observed

        def revision_arrived(access, result, observing):
            revisions.append(time.monotonic() - started)
            return observed(access, result, observing)
        CoordinationAccess.revision_observed = revision_arrived

        def recorded(model, fragments):
            before = {self.label(fragment) for fragment in model.fragments}
            original(model, fragments)
            for fragment in model.fragments:
                first_shown.setdefault(fragment.clipboard_text, time.monotonic() - started)
            after = {self.label(fragment) for fragment in model.fragments}
            if model is not view.messages.model_rows:
                print(f"show on another model: {type(model).__name__} rows={len(model.fragments)}", flush=True)
            if before != after:
                updates.append((time.monotonic() - started, tuple(sorted(after - before)),
                                tuple(sorted(before - after))))
        HistoryRows.show = recorded
        stamp = time.strftime("%H:%M:%S")
        # A row drawn plain before its styled formatting landed: counted per arriving message.
        from pyqt_reactive.widgets.virtual_rows import PlainRow
        delegate = view.messages.rows
        plain: dict[str, int] = {}
        original_formatting = getattr(type(delegate), "styled_formatting", None) or (
            lambda rows, key, fragment, font, width: rows.keyed_formatting(
                key, fragment.clipboard_text, rows.rendering(fragment, font, width)))

        def watched(rows, key, fragment, font, width):
            formatting = original_formatting(rows, key, fragment, font, width)
            if isinstance(formatting, PlainRow) and stamp in fragment.clipboard_text:
                label = " ".join(fragment.clipboard_text.split())[:48]
                plain[label] = plain.get(label, 0) + 1
            return formatting
        type(delegate).styled_formatting = watched
        risen: list[tuple[float, float]] = []
        composer = view.composer
        samples: list[tuple[float, bool, int, bool, int, str]] = []
        scrolls: list[tuple[float, float]] = []

        def sample() -> None:
            window = view.messages
            rising = getattr(window, "arrival_opacity", lambda key: None)  # absent before the fade
            opacities = [opacity for fragment in window.model_rows.fragments
                         if (opacity := rising(fragment.key)) is not None]
            if opacities:
                risen.append((round(time.monotonic() - started, 2), round(min(opacities), 2)))
            scrolls.append((time.monotonic() - started, window.scroll_y))
            samples.append((time.monotonic() - started, composer.submitting.isVisible(),
                            composer.submitting.height(), composer.delivery_controls.isVisible(),
                            view.messages.viewport().height(), composer.submitting.text()[:40]))
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.setInterval(16)
        timer.timeout.connect(sample)
        timer.start()
        # The other party: in a channel, a scratch thread posting to it; in a thread's view, the
        # thread itself replying to the user, the messages that view exists to show.
        sender, recipient = (("scratch-live-pipeline", target) if target.startswith("#")
                             else (target, "user"))
        sender = os.environ.get("SENDER", sender)
        refused: list[str] = []
        posted: dict[int, float] = {}  # when each post's send returned, s after start
        burst = int(os.environ.get("BURST", "3"))  # how many the sender posts at once

        async def post(index: int) -> None:
            # Under a CPU-throttled drive, the sender runs in a scope of its own (SENDER_SCOPE=1):
            # its process start would otherwise spend the app's quota.
            outside = ("systemd-run", "--user", "--scope", "-q") if os.environ.get("SENDER_SCOPE") else ()
            process = await asyncio.create_subprocess_exec(
                *outside, "agent-comms", "send", "--from", sender, "--to", recipient, "--type", "info",
                "--body", f"arrival reply {index} {stamp}",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, error = await process.communicate()
            posted[index] = time.monotonic() - started
            if process.returncode:  # A refused post is a failed walk, never a quiet one.
                refused.append(error.decode(errors="replace").strip()[-200:])
        # How long each arrival-handling call holds the loop: the pager's publish into the rows,
        # a relayout when a row's look lands, and the arrival repaint.
        from toad.qt.history import QtConversationHistory as History, QtHistoryWindow as Window
        held: dict[str, list[float]] = {}
        timed = [(Window, "show_pages"), (Window, "rows_changed"), (Window, "show_draft"),
                 (Window, "keep_reader"), (History, "repaint")]
        originals = [(owner, name, getattr(owner, name)) for owner, name in timed]

        def timing(name, call):
            def wrapper(*arguments, **options):
                begun, worked = time.perf_counter(), time.thread_time()
                try:
                    return call(*arguments, **options)
                finally:
                    held.setdefault(name, []).append(((time.perf_counter() - begun) * 1000,
                                                      (time.thread_time() - worked) * 1000))
            return wrapper
        for owner, name, call in originals:
            setattr(owner, name, timing(name, call))
        scrolled_up = bool(os.environ.get("SCROLLED"))
        window = view.messages
        if scrolled_up:
            # A reader scrolled up: arrivals must not move what they read, and the jump bar shows.
            window.scroll_y = max(0, window.scroll_y - 300)
            await asyncio.sleep(0.5)
            top = window.indexAt(window.viewport().rect().topLeft())
            reading = (self.label(top.data(HistoryRows.FRAGMENT)), window.visualRect(top).top())
        posts = [asyncio.ensure_future(post(index)) for index in range(burst)]
        for index in range(0 if scrolled_up else 3):
            composer.editor.setPlainText(f"arrival send {index} {stamp}")
            composer.submit()
            await asyncio.sleep(0.25)
        await asyncio.gather(*posts)
        if refused:
            raise RuntimeError(f"the scratch sender's posts were refused: {refused}")
        await asyncio.sleep(8.0)
        print("final rows:", view.messages.model_rows.rowCount(),
              [self.label(f) for f in view.messages.model_rows.fragments][-8:], flush=True)
        timer.stop()
        HistoryRows.show = original
        type(delegate).styled_formatting = original_formatting
        appeared: dict[str, list[str]] = {}
        for at, added, removed in updates:
            for text in added:
                appeared.setdefault(text, []).append(f"+{at:.2f}")
            for text in removed:
                appeared.setdefault(text, []).append(f"-{at:.2f}")
            print(f"update {at:6.2f}s +{list(added)} -{list(removed)}", flush=True)
        by_text: dict[str, list[str]] = {}
        for label, marks in appeared.items():
            by_text.setdefault(label.rsplit(" #", 1)[0], []).extend(f"{mark}{label[-5:]}" for mark in marks)
        # Each posted message's wait: from its send returning to its row first showing.
        shown_at = {index: min((at for text, at in first_shown.items()
                                if f"arrival reply {index} {stamp}" in text), default=None)
                    for index in posted}
        print("posted at (s):", sorted(round(at, 2) for at in posted.values()), flush=True)
        print("revisions arrived (s):", [round(at, 2) for at in revisions if at > min(posted.values(), default=0) - 1], flush=True)
        CoordinationAccess.revision_observed = observed
        print("shown at (s):", sorted(round(at, 2) for at in shown_at.values() if at is not None), flush=True)
        waits = sorted(round(shown_at[index] - posted[index], 2) for index in posted if shown_at[index] is not None)
        print(f"burst of {burst}: {len(waits)} shown; wait from send to row (s): "
              f"median {waits[len(waits) // 2] if waits else None}, max {waits[-1] if waits else None}; "
              f"never shown {[index for index in posted if shown_at[index] is None]}", flush=True)
        # A message that leaves the rows after it showed, or shows under two keys, flickers.
        flicker = {text: sorted(marks, key=lambda mark: float(mark[1:].split("#")[0]))
                   for text, marks in by_text.items() if stamp in text and len(marks) > 1}
        toggles = [(round(at, 2), shown, height, controls, viewport, text)
                   for (at, shown, height, controls, viewport, text), previous in zip(samples[1:], samples)
                   if (shown, height, controls, viewport, text) != previous[1:]]
        # A queue row hidden and shown again within a second is the pop out and in.
        hidden = [at for (at, shown, *_), previous in zip(samples[1:], samples) if previous[1] and not shown]
        reshown = [at for (at, shown, *_), previous in zip(samples[1:], samples) if shown and not previous[1]]
        flips = [(round(a, 2), round(b, 2)) for a in hidden for b in reshown if 0 < b - a < 1.0]
        print("queue first/last sample:", samples[:1], samples[-1:], flush=True)
        print("queue/viewport changes (t, summary shown, summary h, controls shown, viewport h):", flush=True)
        for change in toggles:
            print("  ", change, flush=True)
        if scrolled_up:
            row = window.model_rows.row_of(next(f.key for f in window.model_rows.fragments
                                                  if self.label(f) == reading[0]))
            print("scrolled reader: row", reading, "is now at", window.visualRect(window.model_rows.index(row, 0)).top(),
                  "jump bar shown:", window.jump_bar.jump_shown, "following:", window.follows_tail, flush=True)
        jumps = [round(after - before, 1) for (_, before), (_, after) in zip(scrolls, scrolls[1:])
                 if after != before]
        print("rise (t, least opacity of the rising rows):", risen[:6], "...", risen[-3:], flush=True)
        print("scroll steps while following (px per 16 ms):", jumps, flush=True)
        for owner, name, call in originals:
            setattr(owner, name, call)
        # Wall time includes a CPU quota's freezes; thread CPU time is the work itself.
        print("arrival handling per call (calls, wall max ms, CPU median ms, CPU max ms):",
              {name: (len(times), round(max(wall for wall, _ in times), 1),
                      round(sorted(cpu for _, cpu in times)[len(times) // 2], 1), round(max(cpu for _, cpu in times), 1))
               for name, times in held.items()}, flush=True)
        # The 16 ms sampler is late by however long the loop was held: the longest stall.
        gaps = sorted(round((after[0] - before[0]) * 1000) for before, after in zip(samples, samples[1:]))
        print("loop gaps ms (p50, p95, max):", gaps[len(gaps) // 2], gaps[int(len(gaps) * 0.95)], gaps[-1], flush=True)
        near = [round((after[0] - before[0]) * 1000) for before, after in zip(samples, samples[1:])
                if any(at - 0.05 <= after[0] <= at + 0.5 for at, _, _ in updates)]
        print("longest stall within 0.5 s of a history update (ms):", max(near, default=0),
              "elsewhere:", max((round((after[0] - before[0]) * 1000) for before, after in zip(samples, samples[1:])
                                 if not any(at - 0.05 <= after[0] <= at + 0.5 for at, _, _ in updates)), default=0),
              flush=True)
        print("longest gaps (ended at s, ms):", sorted(((round(after[0], 2), round((after[0] - before[0]) * 1000))
                                                      for before, after in zip(samples, samples[1:])),
                                                     key=lambda gap: -gap[1])[:6], flush=True)
        self.report("arrival", updates=len(updates), longest_stall_ms=gaps[-1], flicker=flicker, plain_first_draws=plain, queue_hide_then_show=flips,
                    queue_changes=len(toggles), largest_scroll_step=max(map(abs, jumps), default=0))


class CliSyncScenario(Scenario):
    summary = ("open TARGET (a Claude Code session's thread) and follow TRANSCRIPT (that session's "
               "JSONL, what its CLI shows) for DURATION seconds; every SYNCPROBE-<stamp>-<name> "
               "token is timed when the CLI's transcript gains it and when the Qt view's rows first "
               "show it, and the window is recorded every FRAME_MS ms; prints the lag per token")

    token = r"SYNCPROBE-\d+-[A-Za-z]+\d*"
    width: ClassVar[int] = 412

    def shown_texts(self) -> list[str]:
        """Every row the reader's view holds, saved or still live: the model's own fragments."""
        from toad.qt.history import HistoryRows
        rows = self.page.messages.model_rows
        return [rows.index(row).data(HistoryRows.FRAGMENT).clipboard_text for row in range(rows.rowCount())]

    async def run(self) -> None:
        import json
        import re
        from PySide6.QtCore import QTimer
        target = os.environ["TARGET"]
        transcript = Path(os.environ["TRANSCRIPT"])
        duration = float(os.environ.get("DURATION", "240"))
        frame_ms = int(os.environ.get("FRAME_MS", "200"))
        self.app.resize(self.width, 915)
        await self.listed()
        await self.open(await self.found(lambda row: isinstance(row, ConversationRow)
                                         and target in (row.key, row.target.name),
                                         f"thread {target}", rows=self.thread_rows), target)
        self.report("1-opened", rows=self.page.messages.model_rows.rowCount())
        pattern = re.compile(self.token)
        cli: dict[str, tuple[float, str]] = {}
        qt: dict[str, float] = {}
        frames = self.out / "frames"
        frames.mkdir(exist_ok=True)
        source = transcript.open("rb")
        source.seek(0, os.SEEK_END)
        pending = b""
        frame = 0
        print(f"following {transcript} from byte {source.tell()}; recording every {frame_ms} ms", flush=True)
        # Core asked directly each second, beside the observation the view follows: a token Core
        # serves on asking but the view has not shown is held in the push, not in Core's read.
        import threading
        from agent_comms.nominal.field_codec import FieldCodec
        from agent_comms.transport.tools.reads import TranscriptPageRead
        core_seen: dict[str, float] = {}
        reading = threading.Event()
        reading.set()
        asked = self.app.coordination_access.open_current().core

        def ask_core() -> None:
            while reading.is_set():
                begun = time.time()
                try:
                    text = json.dumps(FieldCodec.encode(asked.call(TranscriptPageRead(thread=target))))
                except Exception as error:  # a failed read is printed, never a quiet gap
                    print(f"core read failed: {error!r}"[:200], flush=True)
                    text = ""
                for name in set(pattern.findall(text)) - core_seen.keys():
                    core_seen[name] = begun
                    print(f"core  {name} at {begun:.3f} (read took {time.time() - begun:.2f}s)", flush=True)
                time.sleep(max(0.0, 1.0 - (time.time() - begun)))
        asker = threading.Thread(target=ask_core, daemon=True)
        asker.start()

        def poll() -> None:
            nonlocal pending
            now = time.time()
            pending += source.read()
            *lines, pending = pending.split(b"\n")
            for line in lines:
                tokens = set(pattern.findall(line.decode(errors="replace")))
                if not tokens:
                    continue
                written = json.loads(line).get("timestamp", "")
                for name in tokens - cli.keys():
                    cli[name] = (now, written)
                    print(f"cli   {name} at {now:.3f} (line stamped {written})", flush=True)
            for text in self.shown_texts():
                for name in set(pattern.findall(text)) - qt.keys():
                    qt[name] = now
                    print(f"qt    {name} at {now:.3f}", flush=True)

        def record() -> None:
            nonlocal frame
            stamp = time.strftime("%H%M%S", time.localtime()) + f"{time.time() % 1:.2f}"[1:]
            self.app.grab().save(str(frames / f"{frame:05d}-{stamp}.jpg"), "JPG", 70)
            frame += 1
        timers = []
        for interval, call in ((50, poll), (frame_ms, record)):
            timer = QTimer()
            timer.setInterval(interval)
            timer.timeout.connect(call)
            timer.start()
            timers.append(timer)
        started = time.monotonic()
        while time.monotonic() - started < duration:
            ends = [name for name in cli if name.endswith("-END")]
            if ends and ends[0] in qt:
                await asyncio.sleep(2.0)
                break
            await asyncio.sleep(0.25)
        for timer in timers:
            timer.stop()
        reading.clear()
        poll()
        rows = []
        for name in sorted(cli, key=lambda name: cli[name][0]):
            seen, written = cli[name]
            lag = None if name not in qt else round((qt[name] - seen) * 1000)
            served = None if name not in core_seen else round((core_seen[name] - seen) * 1000)
            rows.append({"token": name, "cli": round(seen, 3), "line_timestamp": written,
                         "core": core_seen.get(name), "core_ms": served,
                         "qt": qt.get(name), "lag_ms": lag})
            print(f"lag {name}: core {'never' if served is None else f'{served} ms'}, "
                  f"view {'never shown' if lag is None else f'{lag} ms'}", flush=True)
        only_qt = sorted(set(qt) - set(cli))
        (self.out / "sync.json").write_text(json.dumps({"tokens": rows, "qt_only": only_qt}, indent=1))
        lags = sorted(row["lag_ms"] for row in rows if row["lag_ms"] is not None)
        if lags:
            print(f"lag over {len(lags)} tokens: min {lags[0]} ms, median {lags[len(lags) // 2]} ms, "
                  f"max {lags[-1]} ms; {len(rows) - len(lags)} never shown; {frame} frames", flush=True)
        self.report("2-done", tokens=len(rows), shown=len(lags))


class IdleScenario(Scenario):
    summary = ("sit on the welcome sidebar for SETTLE seconds, then open TARGET (#channel or "
               "thread) and sit for DURATION seconds, touching nothing; every 5 s print this "
               "process's CPU use and its busiest threads, the UI's own cost of following the bus")

    @staticmethod
    def thread_ticks() -> dict[str, int]:
        """CPU ticks per thread name, from /proc: utime + stime."""
        ticks: dict[str, int] = {}
        for task in Path("/proc/self/task").iterdir():
            try:
                stat = (task / "stat").read_text()
            except OSError:
                continue
            name = stat[stat.index("(") + 1:stat.rindex(")")]
            fields = stat[stat.rindex(")") + 2:].split()
            ticks[name] = ticks.get(name, 0) + int(fields[11]) + int(fields[12])
        return ticks

    async def sample(self, label: str, seconds: float) -> list[float]:
        hertz = os.sysconf("SC_CLK_TCK")
        shares: list[float] = []
        ended = time.monotonic() + seconds
        while time.monotonic() < ended:
            wall, cpu, before = time.monotonic(), time.process_time(), self.thread_ticks()
            await asyncio.sleep(5.0)
            share = 100 * (time.process_time() - cpu) / (time.monotonic() - wall)
            shares.append(share)
            after = self.thread_ticks()
            busiest = sorted(((after[name] - before.get(name, 0)) / hertz / 5 * 100, name)
                             for name in after)[-3:]
            waves = self.waves
            print(f"{label} cpu {share:5.1f}%  busiest: "
                  + ", ".join(f"{name} {percent:.0f}%" for percent, name in reversed(busiest))
                  + f"  wave: {waves['frames'] / 5:.0f} row repaints/s over {len(waves['rows'])} rows, "
                  f"{waves['moved'] / 5:.0f}/s moved the band", flush=True)
            waves.update(frames=0, moved=0, rows=set())
        return shares

    async def run(self) -> None:
        settle = float(os.environ.get("SETTLE", "60"))
        duration = float(os.environ.get("DURATION", "120"))
        target = os.environ["TARGET"]
        # Each sidebar wave frame repaints its row; a frame whose band covers the same cells as
        # the last one paints the same pixels. Counted, so the sample says what the clock costs.
        waves = {"frames": 0, "moved": 0, "rows": set()}
        spans: dict[int, object] = {}
        original = ConversationRow.repaint

        def counted(row) -> None:
            span = row.wave_span()
            waves["frames"] += 1
            waves["rows"].add(id(row))
            if spans.get(id(row)) != span:
                waves["moved"] += 1
                spans[id(row)] = span
            original(row)
        ConversationRow.repaint = counted
        self.waves = waves
        await self.listed()
        home = await self.sample("home", settle)
        await self.open_named(target)
        self.report("1-opened", rows=self.page.messages.model_rows.rowCount())
        opened = await self.sample(target, duration)
        for label, shares in (("home", home), (target, opened)):
            ordered = sorted(shares)
            print(f"{label}: median {ordered[len(ordered) // 2]:.1f}% cpu, max {ordered[-1]:.1f}% "
                  f"over {len(shares) * 5} s", flush=True)
        self.report("2-done", rows=self.page.messages.model_rows.rowCount())


class PeerProfileScenario(Scenario):
    summary = ("ask PEER (a tailnet machine, at ADDRESS) for a UI profile as the app's own "
               "bus picker does, replacing the profile held for it; prints what the peer answered")

    async def run(self) -> None:
        from agent_comms.transport.tailnet_buses import NamedHost, TailnetPeer
        from agent_comms.transport.tailnet_profiles import TailnetProfiles
        await self.listed()
        found = NamedHost(peer=TailnetPeer(name=os.environ["PEER"], address=os.environ["ADDRESS"], online=True))
        asked = await asyncio.to_thread(self.app.hold_peer_profile, found)
        print(f"peer answered: {type(asked).__name__}; held at {TailnetProfiles.path_for(found)}", flush=True)


class DeliveryPreviewScenario(Scenario):
    summary = ("open TARGET (#scratch), send 2 messages with ui.input.delivery_preview on, then 2 with "
               "it off, turning it off and on live: the queue rows show only while it is on, the info "
               "bar's held count only while it is off, and the history keeps its height while it is off")

    width: ClassVar[int] = 412

    async def run(self) -> None:
        app = self.app
        app.resize(self.width, 915)
        await self.open_named(os.environ.get("TARGET", "#scratch"))
        view = self.page
        composer = view.composer
        samples: list[tuple[bool, bool, bool, int, str]] = []

        def sample() -> None:
            samples.append((composer.submitting.isVisible(), composer.delivery_controls.isVisible(),
                            composer.held.isVisible(), view.messages.viewport().height(), composer.held.text()))
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.setInterval(16)
        timer.timeout.connect(sample)
        stamp = time.strftime("%H:%M:%S")

        async def send(phase: str) -> list[tuple[bool, bool, bool, int, str]]:
            samples.clear()
            timer.start()
            for index in range(2):
                composer.editor.setPlainText(f"delivery preview {phase} {index} {stamp}")
                composer.submit()
                await asyncio.sleep(0.1)
            await asyncio.sleep(6.0)
            timer.stop()
            return list(samples)

        def setting(shown: bool) -> None:
            app.saved_settings.set(SETTINGS.ui.input.delivery_preview, shown)
        faults: list[str] = []
        try:
            setting(True)
            await asyncio.sleep(0.5)
            on = await send("on")
            self.report("1-preview-on", summary_shown=any(s for s, *_ in on),
                        held_shown=any(h for _, _, h, *_ in on))
            if any(h for _, _, h, *_ in on):
                faults.append("the held count showed while the preview was on")
            setting(False)
            await asyncio.sleep(0.5)
            off = await send("off")
            heights = sorted({height for *_, height, _ in off})
            self.report("2-preview-off", summary_shown=any(s for s, *_ in off),
                        controls_shown=any(c for _, c, *_ in off), held=sorted({text for *_, text in off} - {""}),
                        viewport_heights=heights)
            if any(s or c for s, c, *_ in off):
                faults.append("a queue row showed while the preview was off")
            if len(heights) > 1:
                faults.append(f"the history changed height while the preview was off: {heights}")
            setting(True)
            await asyncio.sleep(0.5)
            self.report("3-preview-on-again", held_shown=composer.held.isVisible())
            if composer.held.isVisible():
                faults.append("the held count stayed after the preview came back")
        finally:
            setting(True)
        if faults:
            raise AssertionError("; ".join(faults))


class FrameScenario(Scenario):
    summary = ("frame budget: the GUI thread's stalls and key-to-paint latency (toad.qt.frame_probe) "
               "while idle with the sidebar's waves running, while scrolling #comms, and while typing "
               "into scratch-live-pipeline's composer (never sent); one probe line per phase in "
               "OUT/frame-probe.log")

    width: ClassVar[int] = 412
    phase_seconds: ClassVar[float] = float(os.environ.get("FRAME_SECONDS", "12"))

    def wants(self, phase: str) -> bool:
        """FRAME_PHASES (comma-separated: idle-up, idle-down, scroll, typing) runs only those."""
        chosen = os.environ.get("FRAME_PHASES")
        return not chosen or phase in chosen.split(",")

    async def phase(self, probe, name: str) -> None:
        probe.sink.write(f"--- {name}\n")
        probe.window_start = probe.last = time.perf_counter()
        probe.reset()

    def install_timings(self) -> None:
        """FRAME_TIME_SIDEBAR / FRAME_TIME_HISTORY: time those owners' calls where they run."""
        app = self.app
        timings: dict[str, list[float]] = {}
        if os.environ.get("FRAME_TIME_SIDEBAR"):
            # Measure the sidebar's per-observation work where it runs (tools only).
            from toad.qt import window as qt_window
            def timed(owner, attribute, label):
                original = getattr(owner, attribute)
                def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return original(*args, **kwargs)
                    finally:
                        timings.setdefault(label, []).append((time.perf_counter() - started) * 1000)
                setattr(owner, attribute, wrapper)
            timed(qt_window.Sidebar, "present", "sidebar.present")
            timed(qt_window.Sidebar, "_rebind_groups_from_tree", "rebind_groups")
            timed(qt_window.Sidebar, "redraw", "sidebar.redraw")
            timed(qt_window.Sidebar, "sync", "sidebar.sync")
            timed(type(app), "paint_tabs", "paint_tabs")
            timed(type(app.workspace_sessions.home), "present", "home.present")
            timed(type(app.thread_pane), "bind", "thread_pane.bind")
            timed(type(app.thread_pane), "setting_entries", "thread_pane.setting_entries")
            timed(type(app), "present_panes", "present_panes")
            timed(type(app), "mark_current", "mark_current")
        if os.environ.get("FRAME_TIME_HISTORY"):
            from toad.qt import history as qt_history
            from pyqt_reactive.widgets import virtual_rows
            def timed(owner, attribute, label):
                original = getattr(owner, attribute)
                def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return original(*args, **kwargs)
                    finally:
                        timings.setdefault(label, []).append((time.perf_counter() - started) * 1000)
                setattr(owner, attribute, wrapper)
            for name in ("rows_changed", "show_pages", "prepare_viewport", "respond_to_scroll", "repin_header"):
                if hasattr(qt_history.QtHistoryWindow, name):
                    timed(qt_history.QtHistoryWindow, name, f"window.{name}")
            timed(qt_history.HistoryRows, "show", "rows.show")
            timed(virtual_rows.RowDocumentDelegate, "_row_prepared", "delegate._row_prepared")
        if os.environ.get("FRAME_TIME_OPEN"):
            # What opening a page costs, by owner (tools only).
            from objectstate.lazy_factory import LazyDataclassFactory
            from pyqt_reactive.widgets import virtual_rows
            from toad import object_configuration
            from toad.qt import history as qt_history
            def timed_open(owner, attribute, label):
                original = owner.__dict__[attribute]
                wrap = type(original) if isinstance(original, (staticmethod, classmethod)) else None
                function = original.__func__ if wrap else original
                def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return function(*args, **kwargs)
                    finally:
                        timings.setdefault(label, []).append((time.perf_counter() - started) * 1000)
                setattr(owner, attribute, wrap(wrapper) if wrap else wrapper)
            timed_open(object_configuration.ObjectConfiguration, "__init__", "open.view_configuration")
            timed_open(LazyDataclassFactory, "make_lazy_simple", "open.lazy_type")
            # A settings write, and its two registry-wide parts.
            from objectstate import ObjectStateRegistry
            from toad.preferences import SavedSettings
            timed_open(SavedSettings, "set", "write.settings_set")
            timed_open(ObjectStateRegistry, "_record_snapshot_internal", "write.snapshot")
            timed_open(ObjectStateRegistry, "invalidate_by_type_and_scope", "write.invalidate")
            delegate = virtual_rows.RowDocumentDelegate
            for name in ("sizeHint", "row_document", "measured_height", "_row_prepared", "_rows_prepared",
                         "_update_viewport"):
                if name in delegate.__dict__:
                    timed_open(delegate, name, f"rows.{name}")
            for name in ("rows_changed", "show_pages"):
                timed_open(qt_history.QtHistoryWindow, name, f"window.{name}")
            for name in ("new_document", "final_document"):
                if name in delegate.__dict__:
                    timed_open(delegate, name, f"rows.{name}")
            for name in ("fragment_height", "block_row"):
                timed_open(qt_history.HistoryRowDelegate, name, f"history.{name}")
            # The composer's mount after the first paint, and whether its placeholder held its height.
            from toad.qt.conversation import QtConversation
            timed_open(QtConversation, "mount_composer", "open.composer_mount")
            remember = QtConversation.remember_composer_height

            def compared(view, composer) -> None:
                placeholder = view.composer_heights.get(type(view), view.estimated_composer_height())
                print(f"  composer {type(view).__name__}: placeholder {placeholder}px, built {composer.sizeHint().height()}px (given {composer.height()}px)",
                      flush=True)
                remember(view, composer)
            QtConversation.remember_composer_height = compared
        self.timings = timings

    def write_timings(self, probe) -> None:
        for label, values in sorted(self.timings.items()):
            values.sort()
            probe.sink.write(f"timing {label}: n={len(values)} p50={values[len(values)//2]:.1f}ms "
                             f"max={values[-1]:.1f}ms total={sum(values):.0f}ms\n")

    async def run(self) -> None:
        app = self.app
        self.install_timings()
        app.resize(self.width, 915)
        # A probed run (TOAD_FRAME_PROBE) already has the app's probe, timing each event's
        # delivery; the scenario writes its phases where that probe writes.
        probe = ProbedApplication.probe or FrameProbe(QApplication.instance(), self.out / "frame-probe.log")
        probe.sink = (self.out / "frame-probe.log").open("a", buffering=1)
        probe.REPORT_SECONDS = self.phase_seconds - 0.5
        await self.open_named("#comms")
        app.show_sidebar()
        await asyncio.sleep(2.0)
        forced = self.thread_rows()[:int(os.environ.get("FRAME_WAVES", "4"))]
        for row in forced:
            row.follow_activity(True)
        await asyncio.sleep(0.5)
        waving = [line for line in self.rows(app.sidebar.items()) if line.wave_span() is not None]
        if self.wants("idle-up"):
            await self.phase(probe, f"idle sidebar-up waving={len(waving)}")
            await asyncio.sleep(self.phase_seconds)
        for row in forced:
            row.follow_activity(row.busy)
        app.hide_sidebar()
        await asyncio.sleep(1.0)
        if self.wants("idle-down"):
            await self.phase(probe, "idle sidebar-down #comms")
            await asyncio.sleep(self.phase_seconds)
        window = self.page.messages
        await self.phase(probe, f"scroll #comms rows={window.model_rows.rowCount()}")
        end = time.perf_counter() + (self.phase_seconds if self.wants("scroll") else 0)
        step, steps, started = -60, 0, time.perf_counter()
        while time.perf_counter() < end:
            target = window.scroll_y + step
            if target <= 0 or target >= window.max_scroll_y:
                step = -step
            window.scroll_y = max(0, min(window.max_scroll_y, target))
            steps += 1
            await asyncio.sleep(0.016)
        if steps:
            spent = time.perf_counter() - started
            # A step asks 16 ms of sleep; what it took beyond that is the frame's work.
            probe.sink.write(f"scroll steps={steps} per_step_ms={1000 * spent / steps:.1f} "
                             f"work_per_step_ms={1000 * spent / steps - 16:.1f}\n")
        await asyncio.sleep(1.0)
        await self.open_named("scratch-live-pipeline")
        editor = self.page.composer.editor
        editor.clear()
        editor.setFocus()
        await asyncio.sleep(1.0)
        await self.phase(probe, "typing scratch-live-pipeline")
        end = time.perf_counter() + (self.phase_seconds if self.wants("typing") else 0)
        text = "the quick brown fox jumps over the lazy dog "
        index = 0
        while time.perf_counter() < end:
            char = text[index % len(text)]
            key = Qt.Key.Key_Space if char == " " else getattr(Qt.Key, f"Key_{char.upper()}")
            QApplication.postEvent(editor, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, char))
            QApplication.postEvent(editor, QKeyEvent(QEvent.Type.KeyRelease, key, Qt.KeyboardModifier.NoModifier, char))
            index += 1
            await asyncio.sleep(0.12)
        await asyncio.sleep(0.6)
        typed = editor.toPlainText()
        editor.clear()
        await asyncio.sleep(0.5)
        # As a phone's soft keyboard types: each letter replaces the word being composed
        # (preedit), and a space commits the word.
        await self.phase(probe, "soft-keyboard typing scratch-live-pipeline")
        end = time.perf_counter() + (self.phase_seconds if self.wants("typing") else 0)
        word, index = "", 0
        while time.perf_counter() < end:
            char = text[index % len(text)]
            if char == " ":
                event = QInputMethodEvent("", [])
                event.setCommitString(word + " ")
                word = ""
            else:
                word += char
                event = QInputMethodEvent(word, [])
            QApplication.postEvent(editor, event)
            index += 1
            await asyncio.sleep(0.12)
        await asyncio.sleep(0.6)
        typed += editor.toPlainText()
        editor.clear()
        self.write_timings(probe)
        self.report("done", typed=len(typed))


class ActionsScenario(FrameScenario):
    summary = ("one-off actions as a finger does them, each cold and in its own probe window: open "
               "#comms, expand a channel group, open a thread, switch tabs, open the menu, open "
               "Settings, close it, show the thread pane; the probe's stalls and named slow work "
               "per action in OUT/frame-probe.log (run with TOAD_FRAME_PROBE=1 to time Qt events)")

    settle: ClassVar[float] = float(os.environ.get("ACTION_SETTLE", "3"))

    def tap(self, widget: QWidget, point: QPoint) -> None:
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)

    def tap_row(self, row) -> None:
        tree = self.app.sidebar
        tree.scrollToItem(row)
        self.tap(tree.viewport(), tree.visualItemRect(row).center())

    async def action(self, probe, name: str, act) -> None:
        await self.phase(probe, name)
        started = time.perf_counter()
        result = act()
        if asyncio.iscoroutine(result):
            await result
        took = (time.perf_counter() - started) * 1000
        await asyncio.sleep(self.settle)
        probe.sink.write(f"action {name}: trigger_returned_ms={took:.0f}\n")
        probe.report(time.perf_counter())
        # The owners' calls this action made, then a fresh count for the next one.
        self.write_timings(probe)
        self.timings.clear()

    async def run(self) -> None:
        app = self.app
        app.resize(self.width, 915)
        probe = ProbedApplication.probe or FrameProbe(QApplication.instance(), self.out / "frame-probe.log")
        probe.sink = (self.out / "frame-probe.log").open("a", buffering=1)
        probe.REPORT_SECONDS = 1e9  # one summary per action, written by `action`
        self.install_timings()
        await self.listed()
        await self.channel_row("#comms")
        app.show_sidebar()
        await asyncio.sleep(2.0)
        home = app.workspace_sessions.home
        comms = await self.channel_row("#comms")
        await self.action(probe, "open #comms (tap its row, cold)", lambda: self.tap_row(comms))
        await until(lambda: self.page is not home, "#comms open")
        if any(isinstance(row, ConversationRow) and row.target.name == "#scratch" for row in app.sidebar.items()):
            before = self.page
            scratch = await self.channel_row("#scratch")
            await self.action(probe, "open #scratch (a second channel, cold)",
                              lambda: self.tap_row(scratch))
            await until(lambda: self.page is not before, "#scratch open")
        group = await self.found(lambda row: isinstance(row, ConversationRow) and row.childCount()
                                 and not row.isExpanded(), "closed channel group", rows=app.sidebar.items)
        await self.action(probe, f"expand channel group {group.key}", lambda: app.sidebar.expandItem(group))
        thread = await self.found(lambda row: isinstance(row, ConversationRow) and row.key == "scratch-live-pipeline",
                                  "thread scratch-live-pipeline")
        before = self.page
        await self.action(probe, "open thread scratch-live-pipeline (tap its row, cold)", lambda: self.tap_row(thread))
        await until(lambda: self.page is not before, "thread open")
        tabs = app.tabs
        await self.action(probe, "switch tab to #comms (tap)", lambda: self.tap(tabs, tabs.tabRect(0).center()))
        await self.action(probe, "switch tab back to the thread (tap)", lambda: self.tap(tabs, tabs.tabRect(1).center()))
        await self.action(probe, "open the menu (tap)", lambda: app.menu.click())
        settings = next(command for command, label in ApplicationAction.menu(app) if "settings" in command.declared_name)
        app.menu_panel.hide()
        await self.action(probe, f"open Settings from the menu ({settings.declared_name})", lambda: settings.apply(app))
        await self.action(probe, "close Settings", lambda: next(
            widget for widget in QApplication.topLevelWidgets() + app.findChildren(QWidget)
            if type(widget).__name__.endswith("SettingsScreen") and widget.isVisible()).close())
        def show_thread_pane() -> None:
            app.sidebar_layout.set_collapsed(ThreadSidebarPlacement, not app.sidebar_layout.is_collapsed(ThreadSidebarPlacement))
            app.rearrange_sidebars()
        await self.action(probe, "toggle the thread pane", show_thread_pane)
        self.write_timings(probe)
        self.report("done")


class GoalScenario(Scenario):
    summary = ("open the claude-a DM on a Pixel 8a and read its goal bar: the state line, the "
               "document, the GoalInteraction buttons; collapse and expand it; open its history")

    width: ClassVar[int] = 412
    peer: ClassVar[str] = "claude-a"

    def bar(self) -> QtGoalBar:
        return self.page.findChild(QtGoalBar)

    def buttons(self) -> list[str]:
        return [f"{control.text()}{'' if control.isEnabled() else ' (off)'}"
                for control in self.bar().actions if control.isVisible()]

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        await self.expand("Threads")
        row = await self.found(lambda row: isinstance(row, ConversationRow) and row.target.name == self.peer,
                               f"thread {self.peer}")
        home = app.workspace_sessions.home
        app.open_row(row)
        await until(lambda: self.page is not home and self.bar() is not None, "dm")
        await until(lambda: self.bar().goal_display.visible, "goal")
        await asyncio.sleep(0.5)
        bar = self.bar()
        self.report("1-goal", heading=bar.header.text(), objective=bar.objective.text()[:80],
                    document=bar.document.isVisible(), buttons=self.buttons(),
                    too_wide=PlacementScenario.too_wide(self))
        next(control for control in bar.actions if control.interaction is CollapseInteraction).click()
        await asyncio.sleep(0.5)
        self.report("2-collapsed", document=bar.document.isVisible(), buttons=self.buttons())
        next(control for control in bar.actions if control.interaction is CollapseInteraction).click()
        await asyncio.sleep(0.5)
        self.report("3-expanded", document=bar.document.isVisible(), buttons=self.buttons())
        next(control for control in bar.actions if control.interaction is HistoryInteraction).click()
        await until(lambda: app.findChild(QtGoalHistory) is not None, "history")
        await asyncio.sleep(0.5)
        history = app.findChild(QtGoalHistory)
        self.report("4-history", lines=len(history.findChildren(WrappedText)))
        history.grab().save(str(self.out / "goal-4-history-dialog.png"))
        history.reject()


def shown(value: object) -> object:
    """A setting's value as a report names it: a choice by its class name."""
    return value.__name__ if isinstance(value, type) else value


class SettingsSurface:
    """What the Qt client draws for each app-wide setting that declares an `Effect`, read
    off the open #comms view and the window, so a change shows as a changed reading."""

    def __init__(self, app: QtToadApp, view) -> None:
        self.app, self.view = app, view

    def top_of(self, widget: QWidget) -> int:
        return widget.mapTo(self.app, widget.rect().topLeft()).y()

    def readings(self) -> dict[str, Callable[[], object]]:
        app, view = self.app, self.view
        composer = view.composer
        margins = lambda: (view.layout().contentsMargins().left(), view.layout().contentsMargins().right())
        frame = lambda: tuple(margin for layout in (composer.frame_row, composer.frame.layout())
                              for margin in (layout.contentsMargins().left(), layout.contentsMargins().top()))
        paging = lambda: view.messages.presentation_budget.buffer_viewports
        status = lambda: next(not line.isHidden() for line in view.findChildren(QtStatusLine))
        return {
            "ui.navigation_bar": lambda: "top" if self.top_of(app.tabs) < self.top_of(app.workspace_sessions.pages) else "bottom",
            "ui.theme": lambda: (app.renderer.scheme.name, app.theme.color_scheme.window_bg),
            "ui.message_style": lambda: type(view.message_history.page_source.loader.style).__name__,
            "ui.column": margins, "ui.column_width": margins, "ui.column_alignment": margins,
            "ui.scrollbar": lambda: view.messages.verticalScrollBar().width(),
            "ui.history_buffer_viewports": paging,
            "ui.input.box": frame,
            "ui.input.placeholder": lambda: composer.editor.placeholderText(),
            "ui.input.agent_symbol": lambda: composer.glyph.text(),
            "ui.info_bar": lambda: composer.info_bar.isVisible(),
            "ui.status_line": status,
            "ui.wheel_scroll_rows": lambda: QApplication.wheelScrollLines(),
            "ui.key_mode": lambda: (composer.editor.vim_enabled, type(composer.editor.editing_mode).__name__),
            "ui.sessions_bar": lambda: app.tabs.isVisible(),
            "sidebar.show_stopped": lambda: app.coordination_access.sidebar_interest.show_stopped,
            "sidebar.show_archived": lambda: app.coordination_access.sidebar_interest.show_archived,
            "sidebar.unread_counts": lambda: [app.tabs.tabText(index) for index in range(app.tabs.count())],
            "diff.view": lambda: (type(app.renderer.diff_marks).__name__, view.messages.rows.links_revision),
            "diff.annotations": lambda: (type(app.renderer.diff_marks).__name__, view.messages.rows.links_revision),
            "diff.wrap": lambda: (type(app.renderer.diff_marks).__name__, view.messages.rows.links_revision),
            "ui.keymap.bindings": lambda: sorted(sequence.toString() for shortcut in view.messages._reader_shortcuts
                                                 for sequence in shortcut.keys()),
            "notifications.blink_title": lambda: type(app.input_attention.state).__name__,
        }


class SettingsLiveScenario(Scenario):
    summary = ("change every app-wide setting that declares an Effect, one at a time, as the "
               "settings screen does, and report what Qt draws before and after each")

    @staticmethod
    def read(reading) -> object:
        """A reading, "-" where Qt draws nothing for the setting, or why it can't be read (a
        client that predates the surface the reading names)."""
        if reading is None:
            return "-"
        try:
            return reading()
        except AttributeError as error:
            return f"unreadable: {error}"

    def other_value(self, field):
        """A value this setting does not hold now, of its own kind; for the keymap, page
        down remapped to f9 in the current key mode."""
        value = field.value
        if field.path.value == "ui.column_width":
            return 60 if value == 40 else 40  # columns narrower than the widened conversation
        if field.path.value == "ui.keymap.bindings":
            row = KeymapRow.of(PageDownAction(), self.app.settings.ui.key_mode)
            return self.app.settings.ui.keymap.changed(row, ("f9",)).bindings
        if (choices := field.metadata(FamilyChoices)) is not None:
            return next(choice for choice in choices.choices() if choice is not value)
        if field.path.value == "ui.theme":
            return next(scheme.name for scheme in SCHEMES if scheme.name != value)
        if type(value) is bool:
            return not value
        if type(value) is int:
            return value // 2 if value > 4 else value + 2
        if type(value) is str:
            return value + " (drive)"
        raise LookupError(f"{field.path.value}: no other value of {type(value).__name__} to try")

    async def run(self) -> None:
        app = self.app
        app.resize(1100, 900)  # wide enough that a 40-cell column is narrower than the view
        await self.open_named("#comms")
        surface = SettingsSurface(app, self.page).readings()
        # What the sidebar lists, not the request it sends: hiding stopped threads drops them
        # from the tree once Core presents the sidebar again.
        surface["sidebar.show_stopped"] = surface["sidebar.show_archived"] = lambda: len(self.thread_rows())
        saved = app.saved_settings
        print(f"settings file: {SavedSettings.path()} (exists={SavedSettings.path().exists()})", flush=True)
        for path in saved.state.parameter_structure.leaf_paths():
            field = DeclaredField(saved.state, path)
            if field.metadata(Effect) is None:
                continue
            name = path.value
            if name == "ui.column":
                saved.set(SETTINGS.ui.column_width, 40)  # a column the conversation can show
                await asyncio.sleep(0.5)
            if name == "ui.column_width" and not app.settings.ui.column:
                saved.set(SETTINGS.ui.column, True)
                await asyncio.sleep(0.5)
            reading = surface.get(name)
            if name == "notifications.blink_title":
                app.input_attention.require(self)  # one question waits, as QtQuestion requires
            view_state = self.page.configuration_state
            overridden = name in view_state.editable_paths and view_state.parameters[name] is not None
            before = self.read(reading)
            if name == "ui.theme":
                app.grab().save(str(self.out / "settingslive-theme-before.png"))
            value = self.other_value(field)
            field.edit(value)  # as the settings form edits it
            await asyncio.sleep(4.0 if name.startswith("sidebar.") else 1.0)
            after = self.read(reading)
            if name == "ui.theme":
                app.grab().save(str(self.out / "settingslive-theme-after.png"))
            if name == "notifications.blink_title":
                app.input_attention.release(self)
            verdict = "no Qt surface" if reading is None else ("LIVE" if after != before else "NOT LIVE")
            print(f"{name}: set={shown(value)!r} before={before!r} after={after!r} "
                  f"view_override={overridden} -> {verdict}", flush=True)
        await saved.save()
        app.grab().save(str(self.out / "settingslive-end.png"))


class SettingsReadScenario(Scenario):
    summary = "report every app-wide Effect setting as this launch read it, and what Qt draws for it"

    async def run(self) -> None:
        app = self.app
        app.resize(1100, 900)
        await self.open_named("#comms")
        surface = SettingsSurface(app, self.page).readings()
        saved = app.saved_settings
        print(f"settings file: {SavedSettings.path()} (exists={SavedSettings.path().exists()})", flush=True)
        for path in saved.state.parameter_structure.leaf_paths():
            field = DeclaredField(saved.state, path)
            if field.metadata(Effect) is None:
                continue
            reading = surface.get(path.value)
            print(f"{path.value}: read={shown(field.value)!r} "
                  f"draws={reading() if reading else '-'!r}", flush=True)
        app.grab().save(str(self.out / "settingsread-end.png"))
class HoldScenario(Scenario):
    summary = ("at a Pixel 8a's size, with real touch through the window and the phone's touch-as-mouse "
               "gesture: hold a finger on a sidebar channel, on a history row and on a tab; each that "
               "offers a menu on right-click opens the same menu, and letting go doesn't also tap it. A "
               "hold then a drag scrolls with no menu, and a tap still opens a row")

    @classmethod
    def finger_gesture(cls) -> FingerScrollGesture:
        return TouchAsMouse()

    def __init__(self, app: QtToadApp, out: Path) -> None:
        super().__init__(app, out)
        self.finger = QTest.createTouchDevice()
        self.faults: list[str] = []

    async def touch(self, widget: QWidget, point: QPoint, held_ms: int, moves: tuple[int, ...] = ()) -> None:
        """A finger down at `point` (in `widget`), held for `held_ms`, moved up by each of
        `moves` pixels a frame apart, then lifted, through the window as Android delivers it."""
        window = widget.window()
        handle, at = window.windowHandle(), widget.mapTo(window, point)
        await self.dispatched(lambda: QTest.touchEvent(handle, self.finger).press(0, at).commit())
        await asyncio.sleep(held_ms / 1000)
        for step in moves:
            at = at - QPoint(0, step)
            await self.dispatched(lambda: QTest.touchEvent(handle, self.finger).move(0, at).commit())
            await asyncio.sleep(0.016)
        await self.dispatched(lambda: QTest.touchEvent(handle, self.finger).release(0, at).commit())
        await asyncio.sleep(0.6)

    @staticmethod
    async def dispatched(deliver) -> None:
        """Deliver input through the window from Qt's own dispatch, as the platform does: the
        window processes Qt's events at once, which from inside this scenario's asyncio task
        would enter the loop's other tasks within it."""
        done = asyncio.get_running_loop().create_future()

        def run() -> None:
            deliver()
            done.set_result(None)

        QTimer.singleShot(0, run)
        await done

    def menu(self) -> list[str]:
        """The menu the window shows, row by row, or nothing when it is closed."""
        panel = self.app.menu_panel
        return [row.label.text() for row in panel.findChildren(QtMenuRow)] if panel.isVisible() else []

    def close_menu(self) -> None:
        self.app.menu_panel.hide()

    async def right_click(self, widget: QWidget, point: QPoint) -> list[str]:
        """A mouse's right button at `point`, through the window, where Qt turns it into the
        context-menu request (a widget-level click skips that)."""
        window = widget.window()
        handle, at = window.windowHandle(), widget.mapTo(window, point)
        await self.dispatched(lambda: QTest.mouseClick(handle, Qt.MouseButton.RightButton,
                                                       Qt.KeyboardModifier.NoModifier, at))
        await asyncio.sleep(0.4)
        clicked = self.menu()
        self.close_menu()
        return clicked

    def expect(self, step: str, fact: bool, said: str) -> None:
        if not fact:
            self.faults.append(f"{step}: {said}")

    async def held_menu(self, step: str, widget: QWidget, point: QPoint) -> None:
        """A hold opens the menu a right-click opens there, and its release taps nothing."""
        page = self.page
        # The right-click first: what a mouse offers there before any finger has touched. When
        # a menu panel moves the layout under a held finger, Qt routes the next mouse
        # right-click to the widget that was under that point (Qt's own state, with or without
        # FingerPress), which a phone, having no mouse, never meets.
        clicked = await self.right_click(widget, point)
        # The menu panel sits in the window's layout: the rows return to where they were
        # only once it is gone.
        await asyncio.sleep(0.4)
        await self.touch(widget, point, 1100)
        held = self.menu()
        self.report(step, menu=held)
        self.close_menu()
        await asyncio.sleep(0.4)
        self.expect(step, bool(held), "a held finger opened no menu")
        self.expect(step, held == clicked, f"the hold's menu {held} is not the right-click's {clicked}")
        self.expect(step, self.page is page, f"letting go opened {type(self.page).__name__}")

    async def run(self) -> None:
        app = self.app
        app.resize(412, 915)
        await self.open_named("#comms")
        tree = app.sidebar
        await self.expand("#comms")
        # 1. A sidebar row that isn't open: the hold offers its menu, and letting go doesn't open it.
        other = await self.found(lambda row: isinstance(row, ConversationRow) and row.target.name != "#comms"
                                 and not tree.visualItemRect(row).isEmpty(), "another listed row")
        # Pressed where it is drawn: a row below the visible list would put the finger on
        # whatever is drawn there instead.
        tree.scrollToItem(other)
        await asyncio.sleep(0.3)
        held_on: list[str] = []
        FingerPress.install(QApplication.instance()).long_pressed.connect(
            lambda press: held_on.append(type(press.target).__name__))
        clicked: list[str] = []
        tree.itemClicked.connect(lambda item: clicked.append(item.key))
        # A channel's line has its order control drawn over it: the hold lands on that overlay.
        await self.held_menu("1-sidebar-row", tree.viewport(), tree.visualItemRect(other).center())
        # 1b. A thread's line, which has no control drawn over it.
        thread = await self.found(lambda row: isinstance(row, ConversationRow) and row.parent() is not None
                                  and not tree.visualItemRect(row).isEmpty(), "a listed thread line")
        await self.held_menu("1b-thread-line", tree.viewport(), tree.visualItemRect(thread).center())
        print(f"1-sidebar: held on {held_on}; rows a release clicked {clicked}", flush=True)
        self.expect("1-sidebar", not clicked, f"letting go of a hold clicked {clicked}")
        # 2. A message row in the history: its block menu.
        # A point a third down the rows: a long row's centre can lie off the page, the sticky
        # header covers the top and the floating "back to bottom" bar the bottom, and a hold on
        # either is that control's own press.
        history = self.page.messages
        viewport = history.viewport()
        on_row = QPoint(viewport.width() // 4, viewport.height() // 3)
        self.expect("2-history-row", history.indexAt(on_row).isValid(), "no message row under the held point")
        requested: list[str] = []
        history.block_menu_requested.connect(lambda fragment: requested.append(type(fragment).__name__))
        await self.held_menu("2-history-row", viewport, on_row)
        print(f"2-history-row: block menu asked for {requested}", flush=True)
        # 3. A tab offers no menu on right-click: a hold there stays the tab's press.
        tabs = app.tabs
        await self.touch(tabs, tabs.tabRect(0).center(), 1100)
        self.report("3-tab", menu=self.menu())
        self.expect("3-tab", not self.menu(), f"a tab offered a menu {self.menu()} a right-click doesn't")
        self.close_menu()
        # 4. A hold that then drags scrolls the history, and opens no menu.
        bar = history.verticalScrollBar()
        bar.setValue(bar.maximum())
        await asyncio.sleep(0.4)
        before = bar.value()
        viewport = history.viewport()
        await self.touch(viewport, QPoint(viewport.width() // 2, int(viewport.height() * 0.3)), 300,
                         moves=(-24,) * 14)
        await asyncio.sleep(1.0)
        self.report("4-hold-then-drag", scrolled=(before, bar.value()), menu=self.menu())
        self.expect("4-hold-then-drag", bar.value() != before, "the drag after a short hold didn't scroll")
        self.expect("4-hold-then-drag", not self.menu(), f"the drag opened a menu {self.menu()}")
        self.close_menu()
        # 5. A tap still opens a row.
        page = self.page
        await self.touch(tree.viewport(), tree.visualItemRect(other).center(), 60)
        await until(lambda: self.page is not page and not isinstance(self.page, QtOpeningSessionView), "tapped row")
        self.report("5-tap-opens")
        # 6. A thread's Comms rows (the thread pane) offer Open / Copy, as Textual's do.
        await self.open_named("scratch-live-pipeline")
        # A phone's pane gives the Comms tree under its category toggles little room: a
        # taller window shows its rows.
        app.resize(412, 1600)
        app.thread_side.toggle_pane()
        await asyncio.sleep(1.0)
        picker = app.thread_pane.menu.picker
        picker.setCurrentIndex([picker.itemText(index) for index in range(picker.count())].index("Comms"))
        panel: QtThreadCommsPanel = app.thread_pane._comms_panel
        comms = panel._tree

        def entry_rows():
            return [item for item in comms.findItems("", Qt.MatchFlag.MatchContains | Qt.MatchFlag.MatchRecursive)
                    if panel._row_entry(item) is not None
                    and comms.viewport().rect().contains(comms.visualItemRect(item).center())]

        await until(lambda: comms.isVisible() and entry_rows(), "a Comms relationship row")
        await self.held_menu("6-comms-row", comms.viewport(), comms.visualItemRect(entry_rows()[0]).center())
        if self.faults:
            raise AssertionError("\n".join(self.faults))


class FingerScenario(Scenario):
    summary = ("at a Pixel 8a's width with the phone's touch-as-mouse gesture: drag every visible "
               "scroll area by finger on the welcome, sidebar, #comms, the multi-line composer, the "
               "view-settings picker and its popup, and every menu dialog; tap a sidebar row and a "
               "button inside a scrolled form")

    @classmethod
    def finger_gesture(cls) -> FingerScrollGesture:
        return TouchAsMouse()

    def __init__(self, app: QtToadApp, out: Path) -> None:
        super().__init__(app, out)
        self.tried: set[int] = set()
        self.results: list[tuple[str, str, int, int, int]] = []

    @staticmethod
    def press(widget: QWidget, kind: QEvent.Type, point: QPoint, held: bool) -> None:
        """One mouse event as Qt-for-Android synthesizes it from a finger."""
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
        QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(point), QPointF(widget.mapToGlobal(point)),
                                                   button, buttons, Qt.KeyboardModifier.NoModifier))

    async def drag(self, widget: QWidget, start: QPoint, end: QPoint) -> None:
        self.press(widget, QEvent.Type.MouseButtonPress, start, True)
        await asyncio.sleep(0.016)
        for step in range(1, 13):
            at = start + (end - start) * step / 12
            self.press(widget, QEvent.Type.MouseMove, QPoint(int(at.x()), int(at.y())), True)
            await asyncio.sleep(0.016)
        self.press(widget, QEvent.Type.MouseButtonRelease, end, False)
        await asyncio.sleep(0.8)

    async def tap(self, widget: QWidget, point: QPoint) -> None:
        """A tap once the area under it has stopped moving: a tap on a list still flinging
        stops the fling instead, as Android's own lists do."""
        area = widget
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None:
            await self.settled(lambda: QScroller.scroller(area.viewport()).state() == QScroller.State.Inactive)
        self.press(widget, QEvent.Type.MouseButtonPress, point, True)
        await asyncio.sleep(0.05)
        self.press(widget, QEvent.Type.MouseButtonRelease, point, False)
        await asyncio.sleep(0.6)

    @staticmethod
    async def settled(check, tenths: int = 50) -> bool:
        for _ in range(tenths):
            if check():
                return True
            await asyncio.sleep(0.1)
        return False

    def scrollable(self) -> list[QAbstractScrollArea]:
        return [widget for widget in QApplication.allWidgets()
                if isinstance(widget, QAbstractScrollArea) and widget.isVisible()
                and widget.verticalScrollBar().maximum() > 0 and id(widget) not in self.tried]

    async def exercise(self, step: str) -> None:
        """Drag each scroll area not yet dragged up by most of its viewport, from its centre."""
        shown = [f"{type(area).__name__}:{area.verticalScrollBar().maximum()}" for area in QApplication.allWidgets()
                 if isinstance(area, QAbstractScrollArea) and area.isVisible() and id(area) not in self.tried]
        print(f"  {step}: visible untried scroll areas {shown}", flush=True)
        unheld = [type(area).__name__ for area in QApplication.allWidgets()
                  if isinstance(area, QAbstractScrollArea) and area.isVisible()
                  # Qt names a viewport with no grab CustomGesture; a grab registers its
                  # own recognizer type above it.
                  and QScroller.grabbedGesture(area.viewport()).value <= Qt.GestureType.CustomGesture.value]
        print(f"  {step}: visible scroll areas without the finger grab: {unheld}", flush=True)
        for area in self.scrollable():
            self.tried.add(id(area))
            bar, viewport = area.verticalScrollBar(), area.viewport()
            bar.setValue(bar.minimum())
            await asyncio.sleep(0.2)
            before = bar.value()
            height = viewport.height()
            await self.drag(viewport, QPoint(viewport.width() // 2, int(height * 0.85)),
                            QPoint(viewport.width() // 2, int(height * 0.15)))
            await self.settled(lambda: QScroller.scroller(viewport).state() == QScroller.State.Inactive, tenths=50)
            self.results.append((step, type(area).__name__, bar.maximum(), before, bar.value()))
            print(f"  {step}: {type(area).__name__:28} range={bar.maximum():5} drag {before} -> {bar.value()} "
                  f"{'SCROLLED' if bar.value() != before else 'STUCK'}", flush=True)
            bar.setValue(before)
        self.report(step)

    def close_dialogs(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if widget is not self.app and widget.isVisible():
                widget.close()

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(412, 640)
        await asyncio.sleep(0.5)
        app.show_sidebar()
        await self.channel_row("#comms")
        await self.expand("#comms", "#any")
        await self.exercise("1-welcome-sidebar")
        # A tap on a sidebar row still opens it: the scroller holds the press back, then
        # delivers it when the finger lifts without dragging.
        tree = app.sidebar
        comms = await self.channel_row("#comms")
        tree.scrollToItem(comms)
        await asyncio.sleep(0.3)
        home = app.workspace_sessions.home
        clicked: list[str] = []
        tree.itemClicked.connect(lambda item: clicked.append(getattr(item, "key", "?")))
        await self.tap(tree.viewport(), tree.visualItemRect(comms).center())
        opened = await self.settled(lambda: self.page is not home)
        print(f"  tap on the #comms row: clicked={clicked} {'OPENED' if opened else 'DID NOT OPEN'} "
              f"{type(self.page).__name__}", flush=True)
        if not opened:
            app.open_row(comms)
        await until(lambda: self.page is not home and getattr(self.page, "content_ready", None) is not None
                    and self.page.content_ready.is_set(), "#comms", tenths=150)
        await asyncio.sleep(1.5)
        await self.exercise("2-history")
        composer = self.page.composer.editor
        composer.setPlainText("\n".join(f"line {line} of a long draft, never sent" for line in range(60)))
        await asyncio.sleep(0.3)
        await self.exercise("3-composer")
        composer.clear()
        app.thread_side.toggle_pane()
        await asyncio.sleep(1.0)
        picker = app.thread_pane.menu.picker
        picker.showPopup()
        await asyncio.sleep(0.5)
        await self.exercise("4-picker-popup")
        picker.hidePopup()
        picker.setCurrentIndex(len(panel_specs_for_view(is_session=True)))
        await asyncio.sleep(0.8)
        await self.exercise("5-view-settings")
        app.thread_side.toggle_pane()
        await asyncio.sleep(0.3)
        for command, label in ApplicationAction.menu(app):
            if type(command) is QuitAction:
                continue
            try:
                await command.apply(app)
            except Exception as error:
                print(f"  {label}: FAILED {type(error).__name__}: {error}", flush=True)
                continue
            await asyncio.sleep(3.0)
            # A dialog on the phone is no larger than its screen (ScreenWideWindow).
            for window in QApplication.topLevelWidgets():
                if window is not self.app and window.isVisible():
                    window.resize(min(window.width(), 412), min(window.height(), 640))
            # The keymap opens filtered to the focused widget's keys; every key fills the table.
            for screen in self.app.findChildren(QtKeymapScreen):
                screen.focus_filter.setChecked(False)
            await asyncio.sleep(0.5)
            await self.exercise(f"6-{command.declared_name}")
            if command.declared_name == "settings":
                await self.tap_in_form()
            self.close_dialogs()
            await asyncio.sleep(0.3)
        stuck = [result for result in self.results if result[3] == result[4]]
        print(f"SUMMARY scrolled {len(self.results) - len(stuck)}/{len(self.results)}; "
              f"stuck: {[(step, kind) for step, kind, *_ in stuck]}", flush=True)

    async def tap_in_form(self) -> None:
        """A tap on a button inside a finger-scrolled form still presses it, twice to leave
        the setting as it was."""
        for area in QApplication.allWidgets():
            if not (isinstance(area, QAbstractScrollArea) and area.isVisible()
                    and area.verticalScrollBar().maximum() > 0):
                continue
            buttons = [button for button in area.viewport().findChildren(QAbstractButton)
                       if button.isVisible() and button.isEnabled() and button.isCheckable()
                       and area.viewport().rect().contains(button.mapTo(area.viewport(), button.rect().center()))]
            if not buttons:
                continue
            button = buttons[0]
            # Where a finger presses the button: its own hit area (a check box's indicator).
            spot = next(QPoint(x, y) for y in range(0, button.height(), 2) for x in range(0, button.width(), 2)
                        if button.hitButton(QPoint(x, y)))
            spot = QPoint(spot.x() + 3, spot.y() + 3)
            clicks: list[bool] = []
            button.clicked.connect(lambda checked=False: clicks.append(checked))
            before = button.isChecked()
            await self.tap(button, spot)
            after = button.isChecked()
            await self.tap(button, spot)
            print(f"  tap on {type(button).__name__} {button.objectName() or button.toolTip()[:40]!r} in "
                  f"{type(area).__name__}: checked {before} -> {after} -> {button.isChecked()}; "
                  f"clicked signals {clicks}", flush=True)
            return
        print("  no checkable button visible in a scrolled form", flush=True)


async def drive(scenario: type[Scenario], connection: CoreConnection, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    WirePageBuffer.mark_page = record_mark
    app = await open_app(connection, Checkout(PROJECT), current_scheme(os.environ))
    try:
        await scenario(app, out).run()
    finally:
        # End as the real app does (toad.qt.client_start.serve): the window, then the shared client
        # shutdown; qasync stops the loop when this returns.
        app.close()
        await app.close_client()


def time_settings_writes() -> None:
    """FRAME_TIME_WRITES: each settings write's time, with the registered states and how many
    a write left changed for its snapshot (tools only)."""
    from objectstate import ObjectStateRegistry
    from toad.preferences import SavedSettings
    write = SavedSettings.set

    def timed(self, path, value) -> None:
        states = len(ObjectStateRegistry._states)
        started = time.perf_counter()
        try:
            write(self, path, value)
        finally:
            took = (time.perf_counter() - started) * 1000
            print(f"  settings write {path}: {took:.1f} ms, {states} states", flush=True)
    SavedSettings.set = timed


def main(arguments: list[str]) -> None:
    own = arguments[1:]
    connection = select_connection(own) if len(own) == 4 else None
    if connection is None or len(own) != 2:
        names = "\n".join(f"  {member.declared_name:10} {member.summary}" for member in Scenario.members_with(Scenario))
        raise SystemExit(f"usage: {arguments[0]} SCENARIO OUTDIR (--comms-profile PROFILE | --comms-root ROOT)\n{names}")
    scenario = Scenario.member_named(own[0])
    if os.environ.get("FRAME_TIME_WRITES"):
        time_settings_writes()
    application = FrameProbe.application(arguments[:1])
    install_glyph_fonts(application)  # the entry's splash registers them; this drive has none
    FingerScrolling.install(application, scenario.finger_gesture())
    watch = StrayWindows()
    application.installEventFilter(watch)
    scenario.before_open()
    qasync.run(drive(scenario, connection, Path(own[1])))


if __name__ == "__main__":
    main(sys.argv)
