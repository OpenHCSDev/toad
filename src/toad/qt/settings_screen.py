"""Qt settings screen: the shared `SettingsEditing` screen over Qt's form family.

Pages, search, open-edit registration, finish and discard are inherited from the parent
Textual's `SettingsScreen` inherits; the forms are `toad.qt.forms.QtFormView`. Closing
sends the typed edits and writes the settings file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from toad.qt.forms import QtFormView
from toad.settings_editing import SettingsEditing

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


# The screen.

class QtSettingsScreen(SettingsEditing, QDialog):
    """Modal settings editor: a search above one tab per declared page. Discard rolls
    back unsaved edits; closing sends the typed edits and the app saves them."""

    closed = Signal()

    def __init__(self, app: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.setWindowFlags(Qt.WindowType.Dialog)
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
        for page, form in self.pages.items():
            form.theme(app.renderer)
            self.tabs.addTab(form.widget, page.title or "Settings")
        layout.addWidget(self.tabs, stretch=1)
        buttons = QDialogButtonBox(self)
        buttons.addButton("Discard changes", QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.discard)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

        for form in self.pages.values():
            form.follow_state()
        self.start_editing()

    @property
    def edited_settings(self):
        return self.app.saved_settings

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
