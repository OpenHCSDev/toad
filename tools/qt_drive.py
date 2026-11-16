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
from PySide6.QtWidgets import QApplication

from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.projects.checkouts import Checkout
from toad.client.application_actions import ApplicationAction, QuitAction
from toad.client.connection import RemoteCoreConnection
from toad.qt.main import current_scheme, open_app
from toad.qt.window import ConversationRow, QtToadApp

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
        app.sidebar.expanded.update({"#comms", "Threads"})
        app.sidebar.present()
        await asyncio.sleep(0.3)
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
        app.sidebar.expanded.add("Threads")
        app.sidebar.present()
        await asyncio.sleep(0.3)
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
        self.report("1-menu", actions=[action.text() for action in app.menu_popup.actions()])
        app.menu_popup.close()
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
