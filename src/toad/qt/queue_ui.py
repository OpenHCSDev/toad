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
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import WrappedText

from toad.client.line_blocks import FailureRole, MutedRole
from toad.client.queue_inspection import QueueDeliveryControls, QueueInspectionOwner
from toad.widget_contracts import ActivatesContract
from toad.qt.metrics import UiGap
from toad.motion import ROW_REVEAL, TransitionTarget

# Qt's QWIDGETSIZE_MAX, which PySide does not export: no maximum height.
QWIDGETSIZE_MAX = (1 << 24) - 1

if TYPE_CHECKING:
    from toad.conversation_submission import ConversationSubmissions
    from toad.qt.composer import Composer
    from toad.qt.lines import QtLineRenderer


class QtActivatedText(ActivatesContract, WrappedText):
    """Muted text a press activates (Textual's ``Activates`` + ``SecondaryText``); it wraps."""

    def __init__(self, composer: "Composer", text: str = "") -> None:
        super().__init__(text)
        self.composer = composer
        composer.renderer.themed(self, lambda: self.setStyleSheet(composer.renderer.color_style(MutedRole)))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.activate()
        else:
            super().mousePressEvent(event)


class QtSendNow(QtActivatedText):
    """Textual's ``SendNow``: a press runs the composer's `submit_now`, as Ctrl+Enter does."""

    def activate(self) -> None:
        self.composer.submit_now()


class RowReveal(TransitionTarget):
    """One row under the composer opening or closing its height on the app's clock
    (`ROW_REVEAL`), so the history above it moves smoothly rather than by the row's height in
    one frame. It runs from the height the row has now: a summary that empties and fills again
    (one delivered, the next queued) turns around where it is instead of hiding and showing,
    and one that wraps to more or fewer lines grows or shrinks to them (`resized`)."""

    def __init__(self, row: QWidget, clock, opening: bool) -> None:
        self.row, self.opening = row, opening
        self.start = 0 if row.isHidden() else row.height()
        if opening and row.isHidden():
            row.setFixedHeight(0)
            row.show()
        self.start_transition(clock, ROW_REVEAL)

    @classmethod
    def toggle(cls, row: QWidget, wanted: bool, composer: "Composer") -> None:
        """Show or hide `row` as the shared queue state says, moving only when that changes."""
        running = row.reveal
        if (running.opening if running is not None else not row.isHidden()) == wanted:
            return
        if running is not None:
            running.animation.stop()  # Turned around: the new reveal starts where this one is.
        clock = composer.host.app.animation_clock
        if clock.enabled and composer.isVisible():
            row.reveal = cls(row, clock, wanted)
        else:  # Motion off, or nobody watching: the row is where it is going.
            row.reveal = None
            row.setMinimumHeight(0)
            row.setMaximumHeight(QWIDGETSIZE_MAX)
            row.setVisible(wanted)

    @classmethod
    def resized(cls, row: QWidget, before: int, composer: "Composer") -> None:
        """A shown row whose contents changed its height moves from `before`, the height it
        showed, to its new one; a reveal already running turns toward the new height there."""
        clock = composer.host.app.animation_clock
        if (row.isHidden() or (row.reveal is not None and not row.reveal.opening)
                or not (clock.enabled and composer.isVisible()) or cls.height_of(row) == before):
            return  # A closing row closes; a hidden or unwatched one has nothing to move.
        if row.reveal is not None:
            row.reveal.animation.stop()  # Turned around from the height it has reached.
        row.setFixedHeight(before)  # Held where it was: a layout would take the new height at once.
        row.reveal = cls(row, clock, True)

    @staticmethod
    def height_of(row: QWidget) -> int:
        """The height the row's contents take at its width: a wrapped label's lines."""
        if row.hasHeightForWidth() and row.width() > 0:
            return row.heightForWidth(row.width())
        return row.sizeHint().height()

    @property
    def animation_visible(self) -> bool:
        return self.row.isVisible()

    def apply_amount(self, amount: float) -> None:
        end = self.height_of(self.row) if self.opening else 0
        self.row.setFixedHeight(round(self.start + (end - self.start) * amount))

    def land(self) -> None:
        self.row.reveal = None
        self.row.setMinimumHeight(0)
        self.row.setMaximumHeight(QWIDGETSIZE_MAX)
        self.row.setVisible(self.opening)


class QtQueueSummary(QtActivatedText):
    """The queue summary; a press opens the queue inspection, as Textual's ``QueueSummary``.

    It wraps as Textual's ``AutoHeight`` summary does. Its height opens, closes and follows its
    lines through `RowReveal`: at phone width "Submitting (1): …" and "Delivery (4 visible
    messages): …" wrap to different line counts, and each send popped the history above by a
    line and back in one frame."""

    def __init__(self, composer: "Composer") -> None:
        super().__init__(composer)
        self.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        self.setToolTip("Show queued messages and delivery status.")
        self.reveal: RowReveal | None = None
        self.hide()

    def refresh(self, text: str) -> None:
        if text and text != self.text():  # A closing summary keeps its last words while it closes.
            before = self.height()
            self.setText(text)
            RowReveal.resized(self, before, self.composer)
        RowReveal.toggle(self, bool(text), self.composer)

    def activate(self) -> None:
        """What the shared ``ActivatesContract`` calls — open the queue menu."""
        self.composer.open_queue_menu()


class QtDeliveryControls(QueueDeliveryControls, QWidget, metaclass=PyQtWidgetMeta):
    """Textual's ``DeliveryControls`` row; `QueueDeliveryControls` owns its text."""

    def __init__(self, composer: "Composer") -> None:
        super().__init__(composer)
        self.setWindowFlags(Qt.WindowType.Widget)
        row = QHBoxLayout(self)
        row.setContentsMargins(UiGap.frame, UiGap.tight, UiGap.frame, UiGap.tight)
        row.setSpacing(UiGap.loose)
        row.addWidget(QLabel(self.notice, self), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(QtSendNow(composer, self.send_now_label), 1)
        self.reveal: RowReveal | None = None
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
        renderer.themed(self.error, lambda: self.error.setStyleSheet(renderer.color_style(FailureRole)))
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
