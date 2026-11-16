"""The Qt application host: the shared client's UI-thread, operation and error hooks."""

from __future__ import annotations

import asyncio
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.projects.checkouts import Checkout
from agent_comms.transport.request import CoreAccess
from formbridge.operations import OperationKind
from PySide6.QtCore import qCritical
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)
from pyqt_reactive.core.deferred_callback import DeferredCallback, RepeatingCallback
from pyqt_reactive.services.ui_thread_dispatch import UiThreadDispatcher
from pyqt_reactive.theming import ColorScheme, StatusColorRole, ThemeManager
from pyqt_reactive.widgets.status_line import StatusLine
from ui_theme.scheme import ColourScheme

from toad.client.host import CommandOrigin, CommsHost
from toad.work_preparation import PreparationRuntime


class WindowCommandOrigin(CommandOrigin):
    """The window a command started on; its form opens only while that window is active."""

    def __init__(self, window: QWidget | None) -> None:
        self.window = window

    def current(self) -> bool:
        return QApplication.activeWindow() is self.window

    async def edit(self, definition: TargetAction, title: str, fields: tuple[TargetField, ...],
                   core: CoreAccess) -> dict[str, str | None] | None:
        dialog = QDialog(self.window)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        editors = {field.name: QLineEdit(placeholderText=field.description) for field in fields}
        for field in fields:
            form.addRow(field.label, editors[field.name])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        answer: asyncio.Future[dict[str, str | None] | None] = asyncio.get_running_loop().create_future()
        # A cancelled operation stops waiting; the dialog closing after it answers nobody.
        dialog.accepted.connect(lambda: answer.done() or answer.set_result(
            {name: editor.text() for name, editor in editors.items()}))
        dialog.rejected.connect(lambda: answer.done() or answer.set_result(None))
        dialog.open()
        return await answer


class QtCommsHost(CommsHost, UiThreadDispatcher):
    """The shared host on Qt's event loop; asyncio runs on that loop through qasync.

    The Qt application inherits it beside the shared client and Qt's widget: this host owns
    what the shared client asks of the toolkit (deferred callbacks, timers, operations, errors,
    the clipboard), and its constructor continues to the widget's. Posting onto the UI thread
    is pyqt-reactive's dispatcher, which this host is; timers are its owned callbacks,
    parented to the application; the theme is the shared ui_theme scheme as pyqt-reactive's
    ColorScheme, applied once to the whole QApplication; notices go to its status line.
    Dialogs open over whichever window is active.
    """

    sidebar_show_stopped = False
    sidebar_show_archived = False

    def __init__(self, project: Checkout, preparation: PreparationRuntime, scheme: ColourScheme) -> None:
        self.project_dir = project
        self.preparation = preparation
        self.theme = ThemeManager(ColorScheme.from_theme(scheme))
        self.theme.apply_color_scheme(self.theme.color_scheme)
        self.status_line = StatusLine(self.theme.color_scheme)
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
        running = asyncio.ensure_future(task())
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
        self.status_line.show_status(f"Toad: {type(error).__name__}: {error}", StatusColorRole.ERROR)

    def show_info(self, text: str, title: str) -> None:
        self.status_line.show_status(f"{title}: {text}", StatusColorRole.INFO)

    def show_warning(self, text: str, title: str) -> None:
        self.status_line.show_status(f"{title}: {text}", StatusColorRole.WARNING)

    def show_error(self, error: Exception | str, title: str) -> None:
        self.status_line.show_status(f"{title}: {error}", StatusColorRole.ERROR)

    def log_error(self, text: str) -> None:
        qCritical(text)

    def copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def clear_focus(self) -> None:
        if (focused := QApplication.focusWidget()) is not None:
            focused.clearFocus()

    def capture_command_origin(self) -> WindowCommandOrigin:
        return WindowCommandOrigin(QApplication.activeWindow())

    @property
    def application_running(self) -> bool:
        return not QApplication.closingDown()

    @property
    def display_size(self) -> tuple[int, int]:
        size = QApplication.primaryScreen().size()
        return size.width(), size.height()

    def end_application(self) -> None:
        QApplication.closeAllWindows()
