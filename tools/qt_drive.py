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
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QKeySequence, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QAbstractScrollArea, QDialog, QLabel, QScroller, QStyleOptionViewItem, QApplication, QPushButton, QWidget

from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.registry.thread_presentation import LiveThreadOwnerBinding
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.message_category import MessageCategory
from objectstate import DottedFieldPath
from toad.qt.frame_probe import FrameProbe, ProbedApplication
from toad.client.application_actions import (
    ApplicationAction, NewSessionAction, NewThreadAction, QuitAction, SettingsAction,
)
from toad.qt.settings_screen import QtSettingsScreen
from toad.client.bus_submission import TypedText
from toad.client.conversation import ChannelConversation
from toad.client.connection import CoreConnection
from toad.client.line_blocks import LineLink
from toad.qt.client_start import open_app
from toad.qt.glyph_fonts import install_glyph_fonts
from toad.qt.theme import current_scheme
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
from toad.setting_choices import CenterColumnAlignment
from toad.message_rows import IrcMessageStyle, MarkdownMessageStyle
from toad.client.input_modality import KeyboardInput, TouchInput
from toad.qt.float_layer import QtNoticeCard
from toad.qt.menu import QtMenuRow
from toad.qt.window import ConversationRow, ConversationView, MenuActionRun, QtToadApp
from toad.conversation_turn import LocalTurnBinding
from toad.core.events import TextAgentFail, UnsupportedResumeAgentFail
from toad.live_output import ResponseStream, ThoughtStream
from toad.qt.history import HistoryRows
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
            await self.channel_listed(name)
            await self.expand(name)
            await self.open(self.channel_row(name), name)
        else:
            pending, rows = list(self.app.sidebar.items()), []
            while pending:
                item = pending.pop()
                rows.append(item)
                pending.extend(item.child(index) for index in range(item.childCount()))
            await self.open(next(row for row in rows if isinstance(row, ConversationRow)
                                 and row.target.name == name), name)
        await asyncio.sleep(2.0)

    async def channel_listed(self, name: str) -> None:
        """The sidebar lists this channel: the welcome's first rows can come before it."""
        await until(lambda: any(isinstance(row, ConversationRow) and row.target.name == name
                                for row in self.app.sidebar.items()), name)

    def channel_row(self, name: str) -> ConversationRow:
        return next(row for row in self.app.sidebar.items()
                    if isinstance(row, ConversationRow) and row.target.name == name)

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

    def thread_row(self) -> ConversationRow:
        """The first thread nested under a channel, as the Textual sidebar nests them."""
        for channel in self.app.sidebar.items():
            if isinstance(channel, ConversationRow) and channel.childCount():
                self.app.sidebar.expandItem(channel)
                return channel.child(0)
        raise LookupError("no channel lists a thread")

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
        tops = list(app.sidebar.items())
        comms = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#comms")
        peer = self.thread_row()
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


class ActivityScenario(Scenario):
    summary = "open a working thread's DM (else the first thread); print its info row and activity"

    async def run(self) -> None:
        await self.listed()
        app = self.app
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
        await until(self.thread_rows, "sidebar thread rows")
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
        peer = next(row for row in self.thread_rows() if row.key == wanted)
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
        peer = next(row for row in self.thread_rows() if row.key == wanted)
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
        comms = next(row for row in app.sidebar.items()
                     if isinstance(row, ConversationRow) and row.target.name == "#comms")
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
        app.open_row(self.channel_row("#comms"))
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


class ShippedScenario(Scenario):
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
        await self.step("4-thread", lambda: self.open_named("scratch-live-pipeline"))
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
        await self.open(self.channel_row("#any"), "#any")
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
        return [(type(fragment.events[0]).__name__, fragment.events[0].text)
                for fragment in tail if isinstance(fragment, QtLiveFragment)]

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
        await self.open(self.channel_row("#any"), "#any")
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
        await self.open(self.channel_row("#comms"), "#comms")
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
        await self.open(self.thread_rows()[0], "first thread")
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
            row = next(row for row in self.thread_rows() if row.key == restored_thread.key.name)
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
        tops = list(app.sidebar.items())
        comms = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#comms")
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
        peer = self.thread_row()
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
        tops = list(app.sidebar.items())
        comms = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#comms")
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
        app.open_row(self.thread_row())
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
        await self.channel_listed("#comms")
        await self.expand("#comms")
        self.report("1-welcome", **self.geometry())
        comms = self.channel_row("#comms")
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
        peer = native[0] if native else self.thread_row()
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
        row = self.thread_row() if not name else next(
            line for line in self.rows(tree.items()) if isinstance(line, ConversationRow) and line.key == name)
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

    async def run(self) -> None:
        app = self.app
        app.resize(self.width, 915)
        probe = ProbedApplication.probe or FrameProbe(QApplication.instance(), self.out / "frame-probe.log")
        probe.sink = (self.out / "frame-probe.log").open("a", buffering=1)
        probe.REPORT_SECONDS = 1e9  # one summary per action, written by `action`
        self.install_timings()
        await self.listed()
        await until(lambda: any(isinstance(row, ConversationRow) and row.target.name == "#comms"
                                for row in app.sidebar.items()), "#comms row")
        app.show_sidebar()
        await asyncio.sleep(2.0)
        home = app.workspace_sessions.home
        await self.action(probe, "open #comms (tap its row, cold)", lambda: self.tap_row(self.channel_row("#comms")))
        await until(lambda: self.page is not home, "#comms open")
        if any(isinstance(row, ConversationRow) and row.target.name == "#scratch" for row in app.sidebar.items()):
            before = self.page
            await self.action(probe, "open #scratch (a second channel, cold)",
                              lambda: self.tap_row(self.channel_row("#scratch")))
            await until(lambda: self.page is not before, "#scratch open")
        group = next(row for row in app.sidebar.items()
                     if isinstance(row, ConversationRow) and row.childCount() and not row.isExpanded())
        await self.action(probe, f"expand channel group {group.key}", lambda: app.sidebar.expandItem(group))
        thread = next(row for row in self.rows(app.sidebar.items())
                      if isinstance(row, ConversationRow) and row.key == "scratch-live-pipeline")
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
        row = next(row for row in self.rows(app.sidebar.items())
                   if isinstance(row, ConversationRow) and row.target.name == self.peer)
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
        await until(lambda: any(isinstance(row, ConversationRow) and row.target.name == "#comms"
                                for row in app.sidebar.items()), "#comms listed", tenths=200)
        await self.expand("#comms", "#any")
        await self.exercise("1-welcome-sidebar")
        # A tap on a sidebar row still opens it: the scroller holds the press back, then
        # delivers it when the finger lifts without dragging.
        tree = app.sidebar
        comms = self.channel_row("#comms")
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


def main(arguments: list[str]) -> None:
    own = arguments[1:]
    connection = CoreConnection.select(own) if len(own) == 4 else None
    if connection is None or len(own) != 2:
        names = "\n".join(f"  {member.declared_name:10} {member.summary}" for member in Scenario.members_with(Scenario))
        raise SystemExit(f"usage: {arguments[0]} SCENARIO OUTDIR (--comms-profile PROFILE | --comms-root ROOT)\n{names}")
    scenario = Scenario.member_named(own[0])
    application = FrameProbe.application(arguments[:1])
    install_glyph_fonts(application)  # the entry's splash registers them; this drive has none
    FingerScrolling.install(application, scenario.finger_gesture())
    watch = StrayWindows()
    application.installEventFilter(watch)
    qasync.run(drive(scenario, connection, Path(own[1])))


if __name__ == "__main__":
    main(sys.argv)
