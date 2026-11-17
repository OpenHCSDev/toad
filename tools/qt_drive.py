"""Drive the Qt client offscreen against a live bus and print what it shows.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python tools/qt_drive.py SCENARIO PROFILE OUTDIR

PROFILE is a UI profile (~/.local/state/agent-comms/ui-profiles/NAME.json); OUTDIR gets a
screenshot per step. Each scenario opens the client exactly as `toad.qt.main.serve` does
and prints the state a reader would see, so two runs (before and after a change) compare
line by line. This is the real-application check for the phone client; tests cannot see
what the window draws.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

import qasync
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from agent_comms.messaging.channel_targets import ChannelTarget
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.message_category import MessageCategory
from objectstate import DottedFieldPath
from toad.client.application_actions import ApplicationAction, QuitAction
from toad.client.bus_submission import TypedText
from toad.client.conversation import ChannelConversation
from toad.client.connection import RemoteCoreConnection
from toad.qt.main import current_scheme, open_app
from toad.goal_interactions.controls import CollapseInteraction, HistoryInteraction
from pyqt_reactive.widgets.fitted_text import WrappedText
from toad.qt.goal import QtGoalBar, QtGoalHistory
from toad.qt.placement import QtPlacementControl
from toad.sidebar_layout import DirectionalSidebarPlacementAction, FloatSidebarPlacementAction
from toad.sidebar_placement import (
    BottomSidebarEdge,
    ChannelsSidebarPlacement,
    SidebarEdge,
    ThreadSidebarPlacement,
    TopSidebarEdge,
)
from toad.client.history import ChannelDestination, WirePageBuffer
from toad.qt.command_form import QtCommandForm
from toad.qt.window import ConversationRow, MessageSend, QtToadApp

PROJECT = Path(__file__).resolve().parents[1]


async def until(check, label: str, tenths: int = 200) -> None:
    for _ in range(tenths):
        await asyncio.sleep(0.1)
        if check():
            return
    raise TimeoutError(label)


class Scenario(DeclaredFamily, ABC, affix="Scenario"):
    """One walk through the client; its declared name is the command-line word."""

    summary: ClassVar[str]

    def __init__(self, app: QtToadApp, out: Path) -> None:
        self.app = app
        self.out = out

    @property
    def page(self):
        return self.app.workspace_sessions.pages.currentWidget()

    def tabs(self) -> list[str]:
        return [self.app.tabs.tabText(index) for index in range(self.app.tabs.count())]

    def report(self, step: str, **facts: object) -> None:
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
        await until(lambda: self.page is not before and self.page is not self.app.workspace_sessions.home
                    and self.page.messages.model_rows.rowCount(), label)
        await asyncio.sleep(1.5)

    def channel_row(self, name: str) -> ConversationRow:
        return next(row for row in self.app.sidebar.items()
                    if isinstance(row, ConversationRow) and row.target.name == name)

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
        # Flat thread list moved to QtThreadPanel sibling panel (see window.py);
        # grab the first thread row from that panel.
        peer = next(iter(app._sidebar_thread_panel.items()))
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
        # Flat thread list moved to QtThreadPanel sibling panel (see window.py).
        everyone = app._sidebar_thread_panel.invisibleRootItem()
        rows = app.sidebar.observed.sidebar.threads.rows
        children = [everyone.child(index) for index in range(everyone.childCount())]
        working = [row for row in children if rows[row.key].status.is_working()]
        peer = (working or children)[0]
        app.open_row(peer)
        await until(lambda: self.page is not app.workspace_sessions.home and self.page.status.text(), "status")
        await asyncio.sleep(1.0)
        view = self.page
        activity = view.thread_activity
        self.report("1-opened", peer=peer.key, directory=view.directory.text(), label=view.label.text(),
                    status=view.status.text(), working=activity.working, sweeping=activity.timer.isActive(),
                    rows=view.messages.model_rows.rowCount())


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
        self.report("1-menu", actions=[choice.text() for choice in app.menu_panel.findChildren(QPushButton)])
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
        self.report("3-notice", notice=app.status_line.text(), shown=app.status_line.isVisible())


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
        app.run_operation(MessageSend,
                          lambda: view.submissions.start_bus(TypedText("this send must fail"), destination).prepare())
        await until(lambda: composer.failure.isVisible(), "failure", tenths=100)
        await asyncio.sleep(0.5)
        self.report("6-failed", failure=composer.failure.text(), draft=composer.text,
                    notice=app.status_line.text() if app.status_line.isVisible() else "")


class CommandScenario(Scenario):
    summary = ("run /copy in #any through the shared command catalog, then a refused /copy, "
               "then open #comms' /rename-tag form, fill it and cancel it: nothing is applied, "
               "sent or marked read on the bus, and no teammate's DM is opened")

    form_name: ClassVar[str] = "qt-drive-never-applied"

    def forms(self) -> list[QtCommandForm]:
        return [form for form in self.app.findChildren(QtCommandForm) if form.isVisible()]

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
        await until(lambda: app.status_line.isVisible() and "current target" in app.status_line.text(),
                    "refused", tenths=100)
        self.report("3-refused", notice=app.status_line.text(), shown=app.status_line.isVisible())
        await self.open(self.channel_row("#comms"), "#comms")
        await self.send("/rename-tag")
        await until(self.forms, "form", tenths=150)
        form = self.forms()[0]
        await until(lambda: not form.preparing(), "choices", tenths=150)
        rows = [(row.label.text(), type(row.editor).__name__) for row in form.form.values.values()]
        self.report("4-form", title=form.windowTitle(), rows=rows, confirmation=form.confirmation_text.text(),
                    width=form.minimumSizeHint().width())
        form.grab().save(str(self.out / f"{type(self).declared_name}-4-form.png"))
        editor = form.form.editor(DottedFieldPath("new_name"))
        editor.setText(self.form_name)
        form.form.finish()
        await asyncio.sleep(1.0)
        self.report("5-filled", value=form.arguments(), confirmation=form.confirmation_text.text(),
                    confirmable=form.confirmed.isVisible(), notice=app.status_line.text())
        form.grab().save(str(self.out / f"{type(self).declared_name}-5-filled.png"))
        form.reject()
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


class PlacementScenario(Scenario):
    summary = ("move and float the channels bar, then change the view settings for #comms and "
               "a DM through the thread bar; list anything too wide for a Pixel 8a")

    width: ClassVar[int] = 412

    def too_wide(self) -> list[str]:
        widgets = [self.app, *self.app.findChildren(QWidget)]
        wide = [(widget.minimumSizeHint().width(), widget) for widget in widgets
                if widget.isVisible() and widget.minimumSizeHint().width() > self.width]
        return [f"{width} {type(widget).__name__}" for width, widget in sorted(wide, key=lambda pair: -pair[0])]

    def where(self, pane) -> str:
        parent = pane.parentWidget()
        for name, dock in self.app._docks.items():
            if parent is dock:
                return name
        if parent is self.app.float_layer:
            return "float"
        return "down"

    def placement(self, identity) -> str:
        placed = self.app.sidebar_layout.get(identity)
        return placed.side.declared_name + ("/float" if placed.floating else "")

    def move_control(self, pane, edge: type[SidebarEdge]) -> QtPlacementControl:
        return next(control for control in pane._controls
                    if isinstance(control.action, DirectionalSidebarPlacementAction)
                    and control.action.direction is edge)

    def float_control(self, pane) -> QtPlacementControl:
        return next(control for control in pane._controls
                    if isinstance(control.action, FloatSidebarPlacementAction))

    async def settle(self) -> None:
        await asyncio.sleep(0.5)

    async def opened(self, before) -> None:
        home = self.app.workspace_sessions.home
        await until(lambda: self.page is not before and self.page is not home, "conversation")
        await until(self.page.content_ready.is_set, "content")
        await self.settle()

    async def run(self) -> None:
        await self.listed()
        app = self.app
        app.resize(self.width, 915)
        await self.settle()
        await self.expand("#comms", "Threads")
        tops = list(app.sidebar.items())
        comms = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#comms")
        peer = tops[-1].child(0)
        home = app.workspace_sessions.home
        app.open_row(comms)
        await self.opened(home)
        pane = app.channels_pane
        # The bar is only its toggle and heading; the move arrows and Float live in the pane,
        # as the Textual sidebar draws them. Prove the structure from the widget tree.
        self.report("1-structure",
                    channels_bar=app.channels_bar._title.text(),
                    bar_controls=len(app.channels_bar.findChildren(QtPlacementControl)),
                    pane_controls=len(pane.findChildren(QtPlacementControl)),
                    pane_actions=[control.action.name for control in pane._controls],
                    thread_bar=app.thread_bar._title.text(), too_wide=self.too_wide())
        # Open the channels pane, then move it top, bottom and float it from the pane's own
        # controls: each relocates the one pane over the shared SidebarLayout.
        app.toggle_pane(ChannelsSidebarPlacement)
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
        app.toggle_pane(ChannelsSidebarPlacement)
        await self.settle()
        # The thread bar opens the open conversation's view settings. Toggle one category and
        # read it back off the view: the pane writes the view's own selection, no second copy.
        comms_view = app.workspace_sessions.selected
        category = next(iter(MessageCategory.members_with(MessageCategory)))
        app.toggle_pane(ThreadSidebarPlacement)
        await self.settle()
        before = len(set(comms_view.visible_categories))
        app.thread_pane._checks[category].click()
        await self.settle()
        comms_after = set(comms_view.visible_categories)
        self.report("6-comms-settings", toggled=category.label, where=self.where(app.thread_settings),
                    categories=[control.text() for control in app.thread_pane._checks.values()],
                    before_shown=before, after_shown=len(comms_after),
                    category_shown=(category in comms_after), too_wide=self.too_wide())
        # A DM: its own bar heading and its own, independent view settings.
        app.open_row(peer)
        await self.opened(comms_view)
        dm_view = app.workspace_sessions.selected
        self.report("7-dm-open", thread_heading=app.thread_bar._title.text(),
                    dm_shown=len(set(dm_view.visible_categories)))
        app.thread_pane._checks[category].click()
        await self.settle()
        self.report("8-dm-settings", toggled=category.label,
                    dm_category_shown=(category in dm_view.visible_categories),
                    comms_still=(category in comms_after), where=self.where(app.thread_settings),
                    too_wide=self.too_wide())


class GoalScenario(Scenario):
    summary = ("open the claude-a DM on a Pixel 8a and read its goal bar: the state line, the "
               "document, the GoalInteraction buttons; collapse and expand it; open its history")

    width: ClassVar[int] = 412
    peer: ClassVar[str] = "claude-a"

    def rows(self, items):
        for item in items:
            yield item
            yield from self.rows(item.child(index) for index in range(item.childCount()))

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


async def drive(scenario: type[Scenario], profile: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    WirePageBuffer.mark_page = record_mark
    app = await open_app(RemoteCoreConnection.read(profile), Checkout(PROJECT), current_scheme(os.environ))
    try:
        await scenario(app, out).run()
    finally:
        # Close as the real app does: the window, then the shared client shutdown.
        app.close()
        await app.close_client()
        QApplication.quit()


def main(arguments: list[str]) -> None:
    if len(arguments) != 4:
        names = "\n".join(f"  {member.declared_name:10} {member.summary}" for member in Scenario.members_with(Scenario))
        raise SystemExit(f"usage: {arguments[0]} SCENARIO PROFILE OUTDIR\n{names}")
    scenario = Scenario.member_named(arguments[1])
    QApplication(arguments[:1])
    qasync.run(drive(scenario, Path(arguments[2]), Path(arguments[3])))


if __name__ == "__main__":
    main(sys.argv)
