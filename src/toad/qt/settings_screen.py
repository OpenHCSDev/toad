"""Qt settings screen: the shared `SettingsEditing` screen over Qt's form family.

Pages, search, open-edit registration, finish and discard are inherited from the parent
Textual's `SettingsScreen` inherits; the forms are `toad.qt.forms.QtFormView`. Closing
sends the typed edits and writes the settings file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from formbridge.forms.declared_fields import FormPage

from toad.qt.forms import QtFormView
from toad.settings_editing import SettingsEditing
from toad.qt.presented_window import PresentedWindow

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


# The screen.

class QtSettingsScreen(PresentedWindow, SettingsEditing, QDialog):
    """Modal settings editor: a search above one tab per declared page. Discard rolls
    back unsaved edits; closing sends the typed edits and the app saves them."""

    closed = Signal()

    def __init__(self, app: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.setWindowTitle("Settings")
        self.build_pages()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search settings")
        self.search.textChanged.connect(self.filter_pages)
        layout.addWidget(self.search)
        self.tabs = QTabWidget(self)
        # One empty frame per declared page; a page's form is built into its frame when
        # the page is shown, so opening the screen builds one page, after the screen's
        # frame is on screen.
        self.frames: dict[FormPage, QWidget] = {}
        for page in self.listed:
            frame = QWidget(self.tabs)
            QVBoxLayout(frame).setContentsMargins(0, 0, 0, 0)
            self.frames[page] = frame
            self.tabs.addTab(frame, page.title or "Settings")
        self.tabs.currentChanged.connect(self.show_page)
        layout.addWidget(self.tabs, stretch=1)
        buttons = QDialogButtonBox(self)
        buttons.addButton("Discard changes", QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.discard)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)
        self.start_editing()
        self.first_page_scheduled = False

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """The shown page is built once the screen's own frame has painted: a timer started
        earlier can fire before that paint and hold it behind the page's form."""
        super().paintEvent(event)
        if not self.first_page_scheduled:
            self.first_page_scheduled = True
            QTimer.singleShot(0, self, lambda: self.show_page(self.tabs.currentIndex()))

    def show_page(self, index: int) -> None:
        if index >= 0:
            self.page(tuple(self.listed)[index])

    def page_realized(self, form: QtFormView) -> None:
        form.theme(self.app.renderer)
        form.follow_state()

    def realize_page(self, page: FormPage) -> QtFormView:
        form = super().realize_page(page)
        self.frames[page].layout().addWidget(form.widget)
        return form

    @classmethod
    def form_type(cls):
        return QtFormView

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """Send the typed edits and write the file now. Qt also closes this dialog while the
        application quits, after its loop has stopped: an async save started here would
        never run (and would hold asyncio's shutdown), so the write is synchronous."""
        self.finish()
        self.stop_editing()
        for form in self.pages.values():
            form.leave_state()
        self.edited_settings.save_sync()
        self.closed.emit()
        super().closeEvent(event)
