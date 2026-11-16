"""The Qt application host: the shared client's UI-thread, operation and error hooks."""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from agent_comms.history_views import RetiredViews
from agent_comms.projects.checkouts import Checkout
from formbridge.operations import OperationKind
from formbridge.publications import PublicationStream

from toad.client.host import CommsHost
from toad.client.tab_identity import TabIdentity
from toad.work_preparation import PreparationRuntime


class QtCommsHost(CommsHost):
    """The shared host on Qt's event loop; asyncio runs on that loop through qasync.

    The window owns what is drawn; this host owns what the shared client asks of the
    application: deferred callbacks, timers, operations, errors and the open views.
    Dialogs open over whichever window is active; a timer belongs to whoever holds it.
    """

    tab_names: tuple[TabIdentity, ...] = ()
    sidebar_show_stopped = False
    sidebar_show_archived = False

    def __init__(self, project: Checkout, preparation: PreparationRuntime) -> None:
        self.project_dir = project
        self.preparation = preparation
        self.events = PublicationStream(self)
        self.operations: dict[type[OperationKind], asyncio.Task[None]] = {}

    def schedule_ui(self, callback: Callable[[], None]) -> None:
        QTimer.singleShot(0, callback)

    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> QTimer:
        timer = QTimer()
        timer.timeout.connect(callback)
        timer.start(int(seconds * 1000))
        return timer

    def run_operation(self, kind: type[OperationKind], task: Callable[[], Awaitable[None]]) -> None:
        if kind.exclusive:
            self.cancel_operations(kind)
        self.operations[kind] = asyncio.ensure_future(task())

    def cancel_operations(self, kind: type[OperationKind]) -> None:
        if running := self.operations.pop(kind, None):
            running.cancel()

    @property
    def running_loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def report_fatal(self, error: Exception) -> None:
        traceback.print_exception(error)
        QMessageBox.critical(QApplication.activeWindow(), "Toad", f"{type(error).__name__}: {error}")

    def show_warning(self, text: str, title: str) -> None:
        QMessageBox.warning(QApplication.activeWindow(), title, text)

    def show_error(self, error: Exception | str, title: str) -> None:
        QMessageBox.critical(QApplication.activeWindow(), title, str(error))

    def open_thread_identities(self, root: str) -> set:
        return set()

    def open_channel_targets(self, root: str) -> set[str]:
        return set()

    def retire_views(self, root: Path, retired: RetiredViews) -> None:
        """No tab outlives its thread here: the conversation view rereads on every change."""
