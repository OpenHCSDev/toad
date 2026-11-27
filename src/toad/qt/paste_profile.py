"""Inline Qt panel for pasting a bus-connection profile JSON.

Why inline (QFrame as a child of QtToadApp), not a QDialog: on Qt-for-Android every
QWindow needs its own EGL surface, and allocating one through QRhiBackingStore::flush
races the compositor's deadlock protector (SIGABRT, Pixel 8a tombstone). A frame child
of the main window shares the parent's backing store so the paste surface can open
without the surface-allocation hazard, matching the solution already applied to
`QtMenu` and the removed `QMessageBox` sites in `src/toad/qt/android.py`.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from toad.qt.metrics import UiGap
from toad.qt.tap_flash import QtPushButton


class QtProfilePastePanel(QFrame):
    """A labelled multi-line text input with submit and cancel buttons. `open_for(submit)`
    binds the submit callback and reveals the panel; `hide()` is inherited. The panel
    clears its text on each open so a prior paste is not accidentally reused."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._submit: Callable[[str], object] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.frame, UiGap.frame, UiGap.frame, UiGap.frame)
        layout.setSpacing(UiGap.normal)
        self._prompt = QLabel(
            "Paste the profile JSON the bus owner handed over "
            "(agent-comms-connector grant-ui output)",
            self,
        )
        self._prompt.setWordWrap(True)
        layout.addWidget(self._prompt)
        self._editor = QPlainTextEdit(self)
        self._editor.setPlaceholderText("{...profile JSON...}")
        self._editor.setMinimumHeight(140)
        layout.addWidget(self._editor, 1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(UiGap.frame)
        cancel = QtPushButton("Cancel", self)
        cancel.setFlat(True)
        cancel.setMinimumHeight(40)
        cancel.clicked.connect(self._cancel)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        submit = QtPushButton("Hold profile", self)
        submit.setDefault(True)
        submit.setMinimumHeight(40)
        submit.clicked.connect(self._fire)
        buttons.addWidget(submit)
        layout.addLayout(buttons)
        self.hide()

    def open_for(self, submit: Callable[[str], object]) -> None:
        """Reveal the panel and bind the callback a submit will invoke with the pasted
        text. A previous session's text is cleared so the panel always opens empty."""
        self._submit = submit
        self._editor.clear()
        self.show()
        self._editor.setFocus()

    def _cancel(self) -> None:
        self._submit = None
        self.hide()

    def _fire(self) -> None:
        submit, self._submit = self._submit, None
        self.hide()
        if submit is not None:
            submit(self._editor.toPlainText())
