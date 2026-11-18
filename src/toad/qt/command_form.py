"""A backend command's form on Qt: the shared CommandDraft drawn with pyqt-reactive's
declared form, embedded in a panel (`QtCommandForm`, as Textual's `CommandForm`) or in a
dialog over the window the command started on (`QtCommandDialog`, as `CommandDialog`).

CommandDraft owns the fields, choices, confirmation text and what Apply submits, as it
does for Textual's CommandForm; this module draws them and runs the draft's work as
asyncio tasks on the loop Qt shares with asyncio (qasync). The dialog opens without a
nested event loop, so every other task keeps running while it is up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

from agent_comms.cli_verbs.cli_command import TargetAction
from agent_comms.cli_verbs.target_fields import TargetField
from agent_comms.transport.request import CoreAccess
from formbridge.operations import OperationKind
from objectstate import DottedFieldPath
from pyqt_reactive.forms.declared_form import DeclaredForm
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import WrappedText
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from toad.client.command_draft import CommandFormCore
from toad.client.host import CommandOrigin
from toad.qt.host import QtCommsHost, ScreenWideWindow
from toad.widget_contracts import DismissibleContract, SubmitsContract


class CommandApply(OperationKind):
    """Apply on a command form: confirm its arguments with Core, then answer the form."""


class QtCommandForm(CommandFormCore, QWidget, DismissibleContract, SubmitsContract,
                        metaclass=PyQtWidgetMeta):
    """One backend operation's form, embedded in a panel or presented in a dialog: Qt's
    sibling of Textual's `CommandForm`, over the same `CommandFormCore` Apply flow. Where the
    arguments go (a dialog's answer, the view's settings pane submitting them) and what
    Cancel does are the embedding's."""

    def submit(self) -> None:
        self.apply()

    def __init__(self, host: QtCommsHost, definition: TargetAction, target: str,
                 fields: tuple[TargetField, ...], core: CoreAccess, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.host = host
        self.init_draft(definition, target, fields, core)
        self._alive = True
        loop = asyncio.get_running_loop()
        self.preparation: asyncio.Future[None] = loop.create_future()
        self.preparation.set_result(None)
        self.confirmation: asyncio.Future[None] = loop.create_future()
        self.confirmation.set_result(None)
        title = WrappedText(f"{definition.label} — {target}")
        self.form = DeclaredForm(self.state, host.theme.color_scheme)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form)
        self.confirmation_text = WrappedText()
        self.confirmed = QCheckBox("I confirm this operation", self)
        self.confirmed.hide()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(self.apply)
        buttons.rejected.connect(self.dismiss_control)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.confirmation_text)
        layout.addWidget(self.confirmed)
        layout.addWidget(buttons)

    def release_page(self) -> None:
        """The embedding drops this page: close it and let Qt delete it."""
        self.close_page()
        self.deleteLater()

    def close_page(self) -> None:
        """The page is gone: stop following its draft and its reads."""
        if self._alive:
            self._alive = False
            self.close_draft()
            self.form.leave_state()
            self.preparation.cancel()
            self.confirmation.cancel()

    def apply(self) -> None:
        self.host.run_operation(CommandApply, self.confirm)

    def apply_enabled(self) -> bool:
        return self.apply_button.isEnabled()

    def set_apply_enabled(self, enabled: bool) -> None:
        self.apply_button.setEnabled(enabled)


    # CommandDraft's native hooks

    def draft_alive(self) -> bool:
        return self._alive

    async def draft_run_thread(self, work):
        return await self.host.preparation.run_thread(work)

    def preparing(self) -> bool:
        return not self.preparation.done()

    def start_preparation(self, preparation: Coroutine) -> None:
        self.preparation = asyncio.ensure_future(preparation)
        self.preparation.add_done_callback(self.preparation_ended)

    def preparation_ended(self, task: asyncio.Future[None]) -> None:
        if task.cancelled() or not self.draft_alive():
            return
        try:
            task.result()
        except Exception as error:
            self.preparation_failed(error)
        else:
            self.update_confirmation()

    async def preparation_settled(self) -> bool:
        try:
            await asyncio.shield(self.preparation)
        except Exception:
            # The refresh reported its original error when it ended.
            return False
        return True

    def start_confirmation(self, reading: Coroutine) -> None:
        self.confirmation.cancel()
        self.confirmation = asyncio.ensure_future(reading)
        self.confirmation.add_done_callback(self.confirmation_ended)

    def confirmation_ended(self, task: asyncio.Future[None]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as error:
            self.host.report_fatal(error)

    def reset_confirmed(self) -> None:
        self.confirmed.setChecked(False)

    def show_confirmation(self, text: str, confirmable: bool) -> None:
        self.confirmation_text.setText(text)
        self.confirmed.setVisible(confirmable)

    def is_confirmed(self) -> bool:
        return self.confirmed.isChecked()

    def draft_refused(self) -> bool:
        return self.form.refused

    def draft_failed(self, error: BaseException) -> None:
        self.host.show_error(error, self.definition.label)

    def repaint_choice(self, name: str) -> None:
        self.form.editor(DottedFieldPath(name)).paint()


class QtCommandWindow(ScreenWideWindow, QDialog, DismissibleContract, metaclass=PyQtWidgetMeta):
    """The window a command dialog's form is presented in, over the window it started on;
    dismissing it (Escape, Back, Cancel) closes the dialog unanswered, as Textual's
    `CommandDialog` screen dismisses."""

    dismiss_control = QDialog.reject

    def __init__(self, window: QWidget | None, title: str) -> None:
        super().__init__(window)
        self.setWindowTitle(title)
        QVBoxLayout(self)


class QtCommandDialog(QtCommandForm):
    """The shared operation form in its modal presentation, as Textual's `CommandDialog`:
    it answers once, with the arguments Apply submits, or None when it is cancelled or
    closed."""

    def __init__(self, host: QtCommsHost, window: QWidget | None, definition: TargetAction, target: str,
                 fields: tuple[TargetField, ...], core: CoreAccess) -> None:
        self.answer: asyncio.Future[dict[str, object] | None] = asyncio.get_running_loop().create_future()
        self.dialog = QtCommandWindow(window, definition.label)
        super().__init__(host, definition, target, fields, core, self.dialog)
        self.dialog.layout().addWidget(self)
        self.dialog.fit_screen()
        self.dialog.finished.connect(self.closed)

    def present(self) -> None:
        self.dialog.open()
        self.open_draft()

    async def handle_submission(self, arguments: dict[str, object]) -> None:
        if not self.answer.done():
            self.answer.set_result(arguments)
            self.dialog.accept()

    def dismiss_control(self) -> None:
        self.dialog.dismiss_control()

    def closed(self, _result: int) -> None:
        if not self.answer.done():
            self.answer.set_result(None)
        self.close_page()


class WindowCommandOrigin(CommandOrigin):
    """The window a command started on; its form opens only while that window is active."""

    def __init__(self, host: QtCommsHost) -> None:
        self.host = host
        self.window = QApplication.activeWindow()

    def current(self) -> bool:
        return QApplication.activeWindow() is self.window

    async def edit(self, definition: TargetAction, title: str, fields: tuple[TargetField, ...],
                   core: CoreAccess) -> dict[str, object] | None:
        form = QtCommandDialog(self.host, self.window, definition, title, fields, core)
        form.present()
        return await form.answer
