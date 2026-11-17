"""Qt counterparts of Textual's queue widgets: the clickable queue summary,
the delivery-controls strip shown while Enter queues, and the queue inspection
dialog. State comes from the same ``view.queue_source`` + ``view.submissions``
that Textual reads — Qt just paints and binds."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING

from acp.exceptions import RequestError
from agent_comms.acp_extension import QueueScope
from agent_comms.errors import RelationViolationError, RouteChangedError, UnregisteredThreadError
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
from pyqt_reactive.widgets.fitted_text import WrappedText

from toad.acp.queue_attachment import QueueActionRefused
from toad.client.line_blocks import FailureRole, MutedRole, SpanColumns
from toad.submission_queue import QueueEvidence, QueueSource
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


class QtDeliveryControls(QWidget):
    """The strip shown when Enter queues behind a running turn, mirroring Textual's
    ``DeliveryControls`` label row: a note that Enter queues plus a ``Send now`` button
    bound to the shared ``BusSubmissions.send_now`` worker call."""

    def __init__(self, composer: "Composer") -> None:
        super().__init__(composer)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.composer = composer
        row = QHBoxLayout(self)
        row.setContentsMargins(UiGap.frame, UiGap.tight, UiGap.frame, UiGap.tight)
        row.setSpacing(UiGap.loose)
        self.notice = QLabel("Enter queues · ", self)
        self.send_now_button = QPushButton("Send now (Ctrl+Y)", self)
        self.send_now_button.setToolTip("Send the queued inputs now (Ctrl+Y / Ctrl+Enter).")
        self.send_now_button.clicked.connect(self.composer.send_now)
        row.addWidget(self.notice)
        row.addWidget(self.send_now_button, 1)
        self.hide()


class QtQueueInspection(QDialog):
    """Qt counterpart of ``screens/queue.QueueInspection``: reads queue details from the
    shared ``queue_source`` and binds Send now / Clear to the same async handlers."""

    def __init__(self, submissions: "ConversationSubmissions", renderer: "QtLineRenderer",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Queue and delivery")
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.submissions = submissions
        self.renderer = renderer
        # Base ``BusSubmissions`` doesn't expose ``queue_evidence``/``queue_source``
        # yet — only the ``ConversationSubmissions`` subclass does. The dialog
        # paints a stub until Qt views switch over, so the UI never crashes on a
        # view whose submissions are still the base class.
        self.source: QueueSource | None = getattr(
            getattr(submissions, "view", None), "queue_source", None)
        self.evidence: QueueEvidence | None = (
            submissions.queue_evidence if hasattr(submissions, "queue_evidence") else None)
        self.scope: QueueScope | None = (
            self.source.queue_scope(self.evidence)
            if self.source is not None and self.evidence is not None else None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.frame)

        heading = QLabel("Queue and delivery", self)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)

        self.details = QLabel(self._render_details(), self)
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.details, 1)

        note = QLabel(
            "Editing, deleting and reordering individual queued messages isn't available here.",
            self,
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        # FailureRole owns the error colour + weight in the shared line-blocks family
        # (`toad.client.line_blocks`), pulling from `ui_theme.scheme.ErrorColour`.
        # No Qt-local hex — the shared scheme is the single owner.
        self.error.setStyleSheet(self.renderer.color_style(FailureRole))
        self.error.hide()
        layout.addWidget(self.error)

        self.buttons = QDialogButtonBox(self)
        self.send_now_button = self.buttons.addButton(
            "Send now", QDialogButtonBox.ButtonRole.ApplyRole)
        self.clear_button = self.buttons.addButton(
            "Clear queued inputs", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.close_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        available = (self.source is not None and self.evidence is not None
                     and self.source.queue_actions_available(self.evidence))
        self.send_now_button.setEnabled(available)
        self.clear_button.setEnabled(available)
        self.send_now_button.clicked.connect(self._on_send_now)
        self.clear_button.clicked.connect(self._on_clear)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.buttons)

    def _render_details(self) -> str:
        """Render the shared ``queue_details`` through the Qt line renderer. Falls
        back to a short note when the submissions owner hasn't wired queue evidence
        yet (Qt views still using base ``BusSubmissions``)."""
        if self.source is None or self.evidence is None:
            return (
                "<p>Queue inspection is available once the view's submissions owner "
                "wires <code>queue_evidence</code> (follow-up: Qt views switch to "
                "<code>ConversationSubmissions</code>).</p>"
            )
        block = SpanColumns(self.source.queue_details(self.evidence))
        return self.renderer.html((block,))

    def _on_send_now(self) -> None:
        self._apply_action(self.source.queue_send_now)

    def _on_clear(self) -> None:
        self._apply_action(self.source.queue_clear)

    def _apply_action(self, action: Callable[[QueueEvidence, QueueScope], Awaitable[None]]) -> None:
        """Run the action on the Qt event loop, mirroring Textual's ``QueueInspection``."""
        if self.source is None or self.evidence is None or self.scope is None:
            return
        self.send_now_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        task = asyncio.get_event_loop().create_task(self._run_action(action))
        task.add_done_callback(lambda _t: None)

    async def _run_action(
        self, action: Callable[[QueueEvidence, QueueScope], Awaitable[None]],
    ) -> None:
        assert self.source is not None and self.evidence is not None and self.scope is not None
        try:
            await action(self.evidence, self.scope)
        except (QueueActionRefused, RequestError, RelationViolationError,
                RouteChangedError, UnregisteredThreadError) as error:
            self.error.setText(str(error))
            self.error.show()
            # Re-enable, let the user try again or close.
            available = self.source.queue_actions_available(self.evidence)
            self.send_now_button.setEnabled(available)
            self.clear_button.setEnabled(available)
            return
        self.submissions.publish_pending()
        self.accept()
