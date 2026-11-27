"""The Qt client, loaded once Qt's first frame is up: its window over the bus behind a
connection, and the way every run of it ends (`serve`). The entries (`toad.qt.main` on a
desktop, `toad.qt.android` in the APK) paint the first frame, then load this module."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

import qasync
from agent_comms.projects.checkouts import Checkout
from objectstate import set_base_config_type
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from ui_theme.scheme import ColourScheme

from toad.application_lifetime import ApplicationStart
from toad.client.connection import CoreConnection
from toad.launch_binding import AgentBinding
from toad.launch_opening import LaunchOpening, NoLaunchOpening
from toad.preferences import ToadSettings
from toad.qt.finger_press import FingerPress
from toad.qt.finger_scrolling import FingerScrollGesture, FingerScrolling
from toad.qt.frame_probe import FrameProbe
from toad.qt.window import QtToadApp
from toad.render_processes import RenderProcessPool
from toad.work_preparation import PreparationRuntime

if TYPE_CHECKING:
    # Android's start never loads the desktop's local connection.
    from toad.client.local_connection import ClientLaunch


async def open_app(connection: CoreConnection, project: Checkout, scheme: ColourScheme,
                   agent: str = "", opening: LaunchOpening = NoLaunchOpening()) -> QtToadApp:
    """The Qt client shown over the bus behind ``connection``, its saved tabs read and its
    sidebar observing; ``agent`` is the launch's ``-a``, attached when the connection starts
    agents (`AgentBinding.launched`), as Toad's terminal launch attaches it."""
    set_base_config_type(ToadSettings)
    FingerScrolling.install(QApplication.instance(), FingerScrollGesture.of_platform())
    FingerPress.install(QApplication.instance())
    FrameProbe.start_if_requested(QApplication.instance())
    launch = await AgentBinding.launched(agent, connection.agent_processes)
    app = QtToadApp(connection, project, PreparationRuntime(RenderProcessPool(connection.helper_start)), scheme,
                    launch, opening)
    # The loop outlives the window: closing it starts the shared client shutdown, which
    # runs on this loop, so Qt must not stop the loop when the last window closes.
    QApplication.instance().setQuitOnLastWindowClosed(False)
    await (await app.get_db()).create()
    app.start_client()
    await app.wait_operations(ApplicationStart)
    return app


async def serve(connection: CoreConnection, project: Checkout, scheme: ColourScheme,
                agent: str = "", opening: LaunchOpening = NoLaunchOpening()) -> None:
    """Show the bus behind ``connection`` until Qt is asked to end, then end the way every
    end does: the window closes while its client still serves its views, then the shared
    client shutdown, and qasync stops the loop when this returns.

    Qt 6 answers QCoreApplication.quit() (desktop session end; Android QtActivityBase.onDestroy)
    by closing every window and exiting the event loop within one QEvent.Quit, before the shared
    asyncio client shutdown can run. `ToadApplication.on_quit` intercepts QEvent.Quit directly on
    QApplication.event (zero application-wide event filter overhead) and completes `asked`."""
    app = await open_app(connection, project, scheme, agent, opening)
    application = QApplication.instance()
    asked: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def ask() -> None:
        if not asked.done():
            asked.set_result(None)

    application.on_quit(ask)
    application.lastWindowClosed.connect(ask)
    await asked
    app.close()
    await app.close_client()


class CoalescedQEventLoop(qasync.QEventLoop):
    """A `qasync.QEventLoop` that coalesces zero-delay callbacks (`call_soon`,
    `call_soon_threadsafe`, `Future` completions, `Task.__step`) onto one reusable
    single-shot `QTimer(0)` draining a `deque` snapshot per event-loop turn.

    Stock `qasync._SimpleTimer.add_callback` calls `startTimer(0)` and `killTimer()`
    for every single `call_soon` handle (1,779 OS timer events in 5s during scroll,
    driving `QTimerInfoList::activateTimers()` to 45.3% of Pixel 8a's UI thread).
    """

    def __init__(self, app=None, set_running_loop: bool = False, already_running: bool = False) -> None:
        super().__init__(app, set_running_loop=set_running_loop, already_running=already_running)
        self._ready: deque[asyncio.Handle] = deque()
        self._ready_armed = False
        self._ready_timer = QTimer()
        self._ready_timer.setSingleShot(True)
        self._ready_timer.setInterval(0)
        self._ready_timer.timeout.connect(self._drain_ready)

    def _add_callback(self, handle, delay: float = 0):
        if delay <= 0:
            self._ready.append(handle)
            if not self._ready_armed:
                self._ready_armed = True
                self._ready_timer.start()
            return handle
        return super()._add_callback(handle, delay)

    _DRAIN_BUDGET_SECONDS = 0.002
    _DRAIN_MAX_PASSES = 8

    def _drain_ready(self) -> None:
        self._ready_armed = False
        if asyncio.current_task(self) is not None:
            # Re-entrant QApplication.processEvents() or modal exec() inside a running
            # asyncio Task: defer ready callbacks until the outer Task yields, otherwise
            # stepping another Task raises RuntimeError and drops its wakeup handle.
            if self._ready and not self.is_closed():
                self._ready_armed = True
                self._ready_timer.start()
            return
        ready = self._ready
        deadline = monotonic() + self._DRAIN_BUDGET_SECONDS
        passes = 0
        try:
            while ready and passes < self._DRAIN_MAX_PASSES:
                passes += 1
                for _ in range(len(ready)):
                    handle = ready.popleft()
                    if not handle._cancelled:
                        handle._run()
                if monotonic() >= deadline:
                    break
        finally:
            if ready and not self._ready_armed and not self.is_closed():
                self._ready_armed = True
                self._ready_timer.start()

    def close(self) -> None:
        if not self.is_running() and not self.is_closed():
            self._ready_timer.stop()
            self._ready.clear()
            self._ready_armed = False
        super().close()


def run_qt_loop(coro) -> None:
    """Run ``coro`` on `CoalescedQEventLoop` bound to the active `QApplication`."""
    asyncio.run(coro, loop_factory=lambda: CoalescedQEventLoop(QApplication.instance()))


def serve_launch(launch: ClientLaunch, own: list[str], scheme: ColourScheme) -> None:
    """Serve the Core the desktop entry's ``launch`` selected from its arguments, opening the
    conversation it named, with the project and ``-a`` agent the rest of ``own`` name, until
    the application ends."""
    parser = argparse.ArgumentParser(prog="toad.qt.main")
    parser.add_argument("project", type=Path, nargs="?", default=Path.home())
    parser.add_argument("-a", "--agent", default="", help="The agent New Session starts, as Toad's -a.")
    options = parser.parse_args(own)
    run_qt_loop(serve(launch.connection, Checkout(options.project), scheme, options.agent, launch.opening))
