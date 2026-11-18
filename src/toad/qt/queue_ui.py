"""Qt counterparts of Textual's queue widgets: the clickable queue summary,
the delivery-controls strip shown while Enter queues, and the queue inspection
dialog. State comes from the same ``view.queue_source`` + ``view.submissions``
that Textual reads — Qt just paints and binds."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import WrappedText

from toad.client.line_blocks import FailureRole, MutedRole
from toad.client.queue_inspection import QueueDeliveryControls, QueueInspectionOwner
from toad.widget_contracts import ActivatesContract
from toad.qt.metrics import UiGap

if TYPE_CHECKING:
    from toad.conversation_submission import ConversationSubmissions
    from toad.qt.composer import Composer
    from toad.qt.lines import QtLineRenderer


class QtQueueSummary(ActivatesContract, WrappedText):
    """One-line queue summary; clicking opens the queue inspection, as Textual's
    ``QueueSummary(Activates, ...)`` label does."""

    def __init__(self, composer: "Composer") -> None:
        super().__init__()
        self.composer = composer
        self.setStyleSheet(composer.renderer.color_style(MutedRole))
        self.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        self.setToolTip("Show queued messages and delivery status.")
        self.hide()

    def refresh(self, text: str) -> None:
        self.setText(text)
        self.setVisible(bool(text))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.activate()
        else:
            super().mousePressEvent(event)

    def activate(self) -> None:
        """What the shared ``ActivatesContract`` calls — open the queue menu."""
        self.composer.open_queue_menu()


class QtDeliveryControls(QueueDeliveryControls, QWidget, metaclass=PyQtWidgetMeta):
    """Textual's ``DeliveryControls`` row; `QueueDeliveryControls` owns its text, and the
    button calls the composer's shared send-now."""

    def __init__(self, composer: "Composer") -> None:
        super().__init__(composer)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.composer = composer
        row = QHBoxLayout(self)
        row.setContentsMargins(UiGap.frame, UiGap.tight, UiGap.frame, UiGap.tight)
        row.setSpacing(UiGap.loose)
        self.send_now_button = QPushButton(self.send_now_label, self)
        self.send_now_button.clicked.connect(self.composer.send_now)
        row.addWidget(QLabel(self.notice, self))
        row.addWidget(self.send_now_button, 1)
        self.hide()


class QtQueueInspection(QueueInspectionOwner, QDialog, metaclass=PyQtWidgetMeta):
    """Textual's ``QueueInspection`` as a dialog; `QueueInspectionOwner` owns the reading,
    the actions and how they settle."""

    def __init__(self, submissions: "ConversationSubmissions", renderer: "QtLineRenderer",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.inspect_submissions(submissions)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.frame)
        heading = QLabel(self.title, self)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        # A bus-only submissions owner has no queue evidence: there is no queue to detail.
        details = QLabel(renderer.html((self.details_block(),)) if self.evidence is not None else "", self)
        details.setWordWrap(True)
        details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(details, 1)
        note = QLabel(self.unavailable_note, self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        self.error.setStyleSheet(renderer.color_style(FailureRole))
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(self)
        self.send_now_button = buttons.addButton("Send now", QDialogButtonBox.ButtonRole.ApplyRole)
        self.clear_button = buttons.addButton("Clear queued inputs", QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        self.enable_actions()
        self.send_now_button.clicked.connect(partial(self.run_action, self.send_now))
        self.clear_button.clicked.connect(partial(self.run_action, self.clear_queue))
        layout.addWidget(buttons)

    def enable_actions(self, enabled: bool = True) -> None:
        available = enabled and self.actions_available
        self.send_now_button.setEnabled(available)
        self.clear_button.setEnabled(available)

    def run_action(self, action) -> None:
        self.enable_actions(False)
        asyncio.ensure_future(action())

    def show_queue_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()
        self.enable_actions()

    def close_inspection(self) -> None:
        self.accept()
