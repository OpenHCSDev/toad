"""The Qt application host: the shared client's UI-thread, operation and error hooks."""

from __future__ import annotations

import asyncio
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable

from agent_comms.projects.checkouts import Checkout
from formbridge.operations import OperationKind
from PySide6.QtCore import QUrl, qCritical
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QLayout
from pyqt_reactive.core.deferred_callback import DeferredCallback, RepeatingCallback
from pyqt_reactive.services.ui_thread_dispatch import UiThreadDispatcher
from pyqt_reactive.theming import ColorScheme, StatusColorRole, ThemeManager
from ui_theme.scheme import ColourScheme

from toad.client.commands import CommandRefused
from toad.client.host import CommsHost, Severity, post_crash_to_sink
from toad.client.pending import PendingWork
from toad.work_preparation import PreparationRuntime


_SEVERITY_TO_STATUS_COLOR = {
    "information": StatusColorRole.INFO,
    "warning": StatusColorRole.WARNING,
    "error": StatusColorRole.ERROR,
}


class ScreenWideWindow:
    """A top-level window no wider than its screen's available width (the screen less its
    system bars), whose root layout cannot raise its minimum past that: a page, row or label
    given less than its text shows the overflow itself, through pyqt-reactive's FittedText."""

    def fit_screen(self) -> None:
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.setMaximumWidth(self.screen().availableGeometry().width())


class QtCommsHost(CommsHost, UiThreadDispatcher):
    """The shared host on Qt's event loop; asyncio runs on that loop through qasync.

    The Qt application inherits it beside the shared client and Qt's widget: this host owns
    what the shared client asks of the toolkit (deferred callbacks, timers, operations, errors,
    the clipboard), and its constructor continues to the widget's. Posting onto the UI thread
    is pyqt-reactive's dispatcher, which this host is; timers are its owned callbacks,
    parented to the application; the theme is the shared ui_theme scheme as pyqt-reactive's
    ColorScheme, applied once to the whole QApplication; notices float over the pages in the
    window's float layer (`QtFloatLayer`), each put away after the contract's notice_seconds,
    and an error notice is saved first. An operation the reader waits on shows its work in
    that layer while it runs. Dialogs open over whichever window is active.
    """

    def __init__(self, project: Checkout, preparation: PreparationRuntime, scheme: ColourScheme) -> None:
        self.project_dir = project
        self.preparation = preparation
        self.theme = ThemeManager(ColorScheme.from_theme(scheme))
        self.theme.apply_color_scheme(self.theme.color_scheme)
        self.operations: defaultdict[type[OperationKind], set[asyncio.Future[None]]] = defaultdict(set)
        # The loop qasync runs on Qt's thread. Asked from a worker thread (an observation
        # adopted off the loop, as a bus switch adopts one), get_running_loop has none.
        self._loop = asyncio.get_running_loop()
        super().__init__()

    # Deferred until after the current message, from any thread: the dispatcher's queued post.
    schedule_ui = UiThreadDispatcher.post

    def repeat_ui(self, seconds: float, callback: Callable[[], None]) -> RepeatingCallback:
        return RepeatingCallback(self, int(seconds * 1000), callback)

    def delay_ui(self, seconds: float, callback: Callable[[], None]) -> None:
        DeferredCallback(self, int(seconds * 1000), callback)

    def run_operation(self, kind: type[OperationKind], task: Callable[[], Awaitable[None]]) -> None:
        if kind.exclusive:
            self.cancel_operations(kind)
        running = asyncio.ensure_future(
            self.float_layer.while_pending(PendingWork.for_operation(kind), task()))
        # Named for its kind, so what a running or slow task does reads off the task itself.
        running.set_name(kind.__name__)
        self.operations[kind].add(running)
        running.add_done_callback(self.operations[kind].discard)
        running.add_done_callback(self.operation_finished)

    def operation_finished(self, running: asyncio.Future[None]) -> None:
        """A failed operation reaches the failure owner, as a failed Textual worker does;
        a cancelled one was stopped on purpose."""
        if not running.cancelled() and (error := running.exception()) is not None:
            self.report_fatal(error)

    def cancel_operations(self, kind: type[OperationKind]) -> None:
        for running in self.operations.pop(kind, set()):
            running.cancel()

    async def end_operations(self) -> None:
        running = tuple(task for tasks in self.operations.values() for task in tasks)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    async def wait_operations(self, kind: type[OperationKind]) -> None:
        await asyncio.gather(*tuple(self.operations[kind]), return_exceptions=True)

    @property
    def running_loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def report_fatal(self, error: Exception) -> None:
        traceback.print_exception(error)
        super().report_fatal(error)

    def notify(self, message: str, *, title: str = "",
               severity: Severity = "information",
               markup: bool = True, sound: str | None = None) -> None:
        """Qt floats every notice over the pages, coloured by severity, as Textual floats its
        toasts; the content under it never moves. The shared `show_info`/`show_warning`/
        `show_error` on CommsHost dispatch here, and so does anything calling `self.notify`."""
        text = f"{title}: {message}" if title else message
        self.float_layer.post(text, _SEVERITY_TO_STATUS_COLOR[severity], self.notice_seconds)

    def log_error(self, text: str) -> None:
        qCritical(text)

    def copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def open_channel_sort(self, channel: str) -> None:
        raise CommandRefused("Sorting a channel's members isn't in this client yet")

    def clear_focus(self) -> None:
        if (focused := QApplication.focusWidget()) is not None:
            focused.clearFocus()

    @property
    def application_running(self) -> bool:
        return not QApplication.closingDown()

    @property
    def display_size(self) -> tuple[int, int]:
        size = QApplication.primaryScreen().size()
        return size.width(), size.height()

    def end_application(self) -> None:
        QApplication.closeAllWindows()
