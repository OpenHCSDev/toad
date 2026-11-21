"""The Qt client, loaded once Qt's first frame is up: its window over the bus behind a
connection, and the way every run of it ends (`serve`). The entries (`toad.qt.main` on a
desktop, `toad.qt.android` in the APK) paint the first frame, then load this module."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import qasync
from agent_comms.projects.checkouts import Checkout
from objectstate import set_base_config_type
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from ui_theme.scheme import ColourScheme

from toad.application_lifetime import ApplicationStart
from toad.client.connection import CoreConnection
from toad.launch_binding import AgentBinding
from toad.launch_opening import LaunchOpening, NoLaunchOpening
from toad.qt.finger_press import FingerPress
from toad.qt.finger_scrolling import FingerScrollGesture, FingerScrolling
from toad.qt.frame_probe import FrameProbe
from toad.qt.window import QtToadApp
from toad.render_backend import Renderer
from toad.render_processes import RenderProcessPool
from toad.render_socket_service import AndroidRenderService
from toad.work_preparation import PreparationRuntime

if TYPE_CHECKING:
    # Android's start never loads the desktop's local connection.
    from toad.client.local_connection import ClientLaunch


def _renderer_for_platform(connection: CoreConnection) -> Renderer:
    """The platform's real process primitive behind one renderer contract.

    Qt row work is data-only. Desktop uses CPython's process pool; Android, which
    has no ``_multiprocessing``, uses the app's p4a Python service process.
    """
    if QGuiApplication.platformName() == "android":
        return AndroidRenderService()
    return RenderProcessPool(connection.helper_start)


@dataclass(frozen=True)
class QtClientSettings:
    """The Qt client's settings root. It holds no settings yet; ObjectState needs one root
    type named for the process before it holds any object, such as a command form's draft.
    Toad's Textual settings root lives in a module that needs Textual."""


async def open_app(connection: CoreConnection, project: Checkout, scheme: ColourScheme,
                   agent: str = "", opening: LaunchOpening = NoLaunchOpening()) -> QtToadApp:
    """The Qt client shown over the bus behind ``connection``, its saved tabs read and its
    sidebar observing; ``agent`` is the launch's ``-a``, attached when the connection starts
    agents (`AgentBinding.launched`), as Toad's terminal launch attaches it."""
    set_base_config_type(QtClientSettings)
    FingerScrolling.install(QApplication.instance(), FingerScrollGesture.of_platform())
    FingerPress.install(QApplication.instance())
    FrameProbe.start_if_requested(QApplication.instance())
    launch = await AgentBinding.launched(agent, connection.agent_processes)
    app = QtToadApp(connection, project, PreparationRuntime(_renderer_for_platform(connection)), scheme,
                    launch, opening)
    # The loop outlives the window: closing it starts the shared client shutdown, which
    # runs on this loop, so Qt must not stop the loop when the last window closes.
    QApplication.instance().setQuitOnLastWindowClosed(False)
    await (await app.get_db()).create()
    app.start_client()
    await app.wait_operations(ApplicationStart)
    return app


class EndRequest(QObject):
    """Qt was asked to end the application: its last window closed, or something called
    QCoreApplication.quit() (a desktop session ending; on Android, QtActivityBase.onDestroy
    when the app is swiped from recents, which then blocks Android's main thread until
    Python's main returns).

    Qt 6 answers a quit by closing every window and leaving its event loop within that one
    event. The loop is the client's asyncio loop, so the shared client shutdown had no loop
    left to run on: the wakeup the closed window queued ran after qasync stopped
    (`Task.task_wakeup ... is not the running loop`), asyncio.run's cancellation then waited
    on a task that could no longer wake, and Android killed the app for not answering. The
    request is taken here instead: it completes ``asked``, and the client ends itself.
    """

    def __init__(self, asked: asyncio.Future[None]) -> None:
        super().__init__()
        self.asked = asked

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Quit:
            self.ask()
            return True
        return False

    def ask(self) -> None:
        if not self.asked.done():
            self.asked.set_result(None)


async def serve(connection: CoreConnection, project: Checkout, scheme: ColourScheme,
                agent: str = "", opening: LaunchOpening = NoLaunchOpening()) -> None:
    """Show the bus behind ``connection`` until Qt is asked to end, then end the way every
    end does: the window closes while its client still serves its views, then the shared
    client shutdown, and qasync stops the loop when this returns. Desktop passes the
    process-decoding member, Android the one decoding in place."""
    app = await open_app(connection, project, scheme, agent, opening)
    application = QApplication.instance()
    request = EndRequest(asyncio.get_running_loop().create_future())
    application.installEventFilter(request)
    application.lastWindowClosed.connect(request.ask)
    await request.asked
    app.close()
    await app.close_client()


def serve_launch(launch: ClientLaunch, own: list[str], scheme: ColourScheme) -> None:
    """Serve the Core the desktop entry's ``launch`` selected from its arguments, opening the
    conversation it named, with the project and ``-a`` agent the rest of ``own`` name, until
    the application ends."""
    parser = argparse.ArgumentParser(prog="toad.qt.main")
    parser.add_argument("project", type=Path, nargs="?", default=Path.home())
    parser.add_argument("-a", "--agent", default="", help="The agent New Session starts, as Toad's -a.")
    options = parser.parse_args(own)
    qasync.run(serve(launch.connection, Checkout(options.project), scheme, options.agent, launch.opening))
