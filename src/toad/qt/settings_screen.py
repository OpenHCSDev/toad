"""Qt settings screen backed directly by ``pyqt_reactive.ConfigWindow`` (OpenHCS blueprint).

Replaces the hand-rolled ``QDialog`` / ``QTabWidget`` / ``QtFormView`` host with
``ToadConfigWindow``, preserving ``PresentedWindow`` lifecycle and ``SettingsEditing``
ownership while gaining live hierarchy navigation, reset-to-inherited, Help, and View Code.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from toad.qt.config_window import (
    ConfigSaveParticipant,
    ConfigWindowTabSpec,
    ToadConfigWindow,
)
from toad.qt.forms import QtFormView
from toad.qt.window import QtToadApp
from toad.settings_editing import SettingsEditing


class QtSettingsScreen(SettingsEditing, ToadConfigWindow):
    """Modal settings editor hosted by ``pyqt_reactive.ConfigWindow``."""

    closed = Signal()

    def __init__(self, app: QtToadApp, parent: QWidget | None = None) -> None:
        self.app = app
        self.pages = {}
        self.listed = {}
        save_participant = ConfigSaveParticipant(
            apply=lambda _config: self.edited_settings.save_sync(),
            rollback=lambda _config: self.edited_settings.discard(),
        )
        super().__init__(
            tabs=(
                ConfigWindowTabSpec(
                    state=self.edited_settings.state,
                    save_participant=save_participant,
                ),
            ),
            parent=parent or app,
            scope_id=self.edited_settings.state.scope_id,
            title_text="Settings",
        )
        self.resize(980, 720)
        self.start_editing()

    @classmethod
    def form_type(cls):
        return QtFormView

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.finish()
        if self.finish in self.edited_settings.open_edits:
            self.stop_editing()
        self.edited_settings.save_sync()
        self.closed.emit()
        super().closeEvent(event)
