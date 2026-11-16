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
from toad.client.application_actions import ApplicationAction, QuitAction
from toad.client.bus_submission import TypedText
from toad.client.conversation import ChannelConversation
from toad.client.connection import RemoteCoreConnection
from toad.qt.main import current_scheme, open_app
from toad.qt.window import ConversationRow, MessageSend, QtToadApp, ViewDestination

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
        await self.expand("#comms", "Threads")
        tops = list(app.sidebar.items())
        comms = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#comms")
        peer = tops[-1].child(0)
        app.open_row(comms)
        await until(lambda: self.page is not app.workspace_sessions.home and self.page.messages.toPlainText(), "#comms")
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
        await self.expand("Threads")
        everyone = list(app.sidebar.items())[-1]
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
                    message_chars=len(view.messages.toPlainText()))


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


class MissingChannelDestination(ViewDestination):
    """A destination its view still shows whose channel Core does not know: its read-only
    check fails before anything leaves, the way a refused send does."""

    def shown(self) -> bool:
        return True


class ComposerScenario(Scenario):
    summary = ("type @ and / in #any without sending, then force a send to the scratch channel "
               "#composer-drive-missing, which Core does not know, so it fails before it leaves: "
               "the drive puts nothing on the bus and writes to no teammate")

    async def type(self, text: str) -> None:
        composer = self.page.composer
        composer.editor.clear()
        composer.editor.setFocus()
        composer.editor.insertPlainText(text)
        await asyncio.sleep(0.2)

    async def open(self, row, label: str) -> None:
        before = self.page
        self.app.open_row(row)
        await until(lambda: self.page is not before and self.page is not self.app.workspace_sessions.home
                    and self.page.messages.toPlainText(), label)
        await asyncio.sleep(1.5)

    async def run(self) -> None:
        await self.listed()
        app = self.app
        await self.expand("Threads")
        tops = list(app.sidebar.items())
        everyone = next(row for row in tops if isinstance(row, ConversationRow) and row.target.name == "#any")
        await self.open(everyone, "#any")
        composer = self.page.composer
        self.report("1-any", placeholder=composer.editor.placeholderText(),
                    activity=[line.text() for line in self.page.activity])
        await self.type("@")
        await until(lambda: composer.offers.offers, "mention offers", tenths=100)
        self.report("2-mentions", offers=[offer.label for offer in composer.offers.offers])
        composer.offers.accept_current()
        self.report("3-mention-accepted", text=composer.text)
        await self.type("/")
        await until(lambda: composer.offers.offers, "command offers", tenths=300)
        self.report("4-commands", count=len(composer.offers.offers),
                    offers=[offer.label for offer in composer.offers.offers[:8]])
        await self.type("/te")
        self.report("5-commands-te", offers=[offer.label for offer in composer.offers.offers[:5]])
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


async def drive(scenario: type[Scenario], profile: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
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
