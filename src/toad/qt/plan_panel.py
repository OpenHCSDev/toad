"""Qt rendering of the shared `Plan` sidebar panel.

The plan's data and the completion-transition decision live on
`AgentController.plan_display` (shared `PlanDisplayState` instance per agent). This
module owns only the Qt rendering: a column of rows, one per entry, with the status
marker on the left and the entry text on the right. Opacity follows `PlanStatus.opacity`;
completed rows show the text struck through. An empty roster shows the italic "No plan
yet" line.

Subscribes to `core_events.Plan` on the bound view's agent only to trigger a repaint;
the entries + newly-complete answer are read from `controller.plan_display` each render,
so Qt holds no parallel entries/previous-status roster.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from toad.core import events as core_events
from toad.plan import PlanItem, PlanView
from toad.qt.session_panel import SessionPanel
from toad.qt.metrics import UiGap
from toad.thread_sidebar_declarations import PlanSidebarPanel


class QtPlan(PlanView, SessionPanel, QWidget):
    panel_type = PlanSidebarPanel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.frame)
        self._column.setSpacing(UiGap.tight)
        self._column.addStretch(1)
        self._subscription = None
        self._render()

    def bind(self, view) -> None:
        """Follow a new agent view: unsubscribe the old agent's Plan events and
        subscribe to future Plan updates on the new agent's event bus. Entries are
        read fresh from `controller.plan_display` on each render — no local cache.

        `_view` + the `present()` trigger come from `SessionPanel.bind`; this
        override wraps that with the subscription-cycle lifecycle."""
        self._drop_subscription()
        super().bind(view)
        self._subscription = view.bound_agent.events.subscribe(core_events.Plan, self._on_plan)

    def present(self) -> None:
        """Repaint. Called by `SessionPanel.bind` and by `_on_plan`."""
        self._render()

    def _on_plan(self, event: core_events.Plan, subscription: object) -> None:
        self._render()

    def _drop_subscription(self) -> None:
        subscription, self._subscription = self._subscription, None
        if subscription is not None:
            subscription.close()

    def _clear_rows(self) -> None:
        # Keep the final addStretch(1) anchor at the end of the column.
        while self._column.count() > 1:
            item = self._column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        self._clear_rows()
        entries = self._view.bound_agent.plan_entries
        if not entries:
            empty = QLabel(self.empty_plan_text, self)
            font = empty.font()
            font.setItalic(True)
            empty.setFont(font)
            empty.setEnabled(False)  # dim via the palette's disabled text role
            self._column.insertWidget(0, empty)
            return
        for index, (marker, entry) in enumerate(self.plan_rows(entries)):
            row = self._build_row(marker, entry)
            self._column.insertWidget(index, row)

    def _build_row(self, marker_text: str, entry: PlanItem) -> QWidget:
        row = QWidget(self)
        row.setWindowFlags(Qt.WindowType.Widget)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UiGap.normal)
        marker = QLabel(marker_text, row)
        text = QLabel(entry.content, row)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        entry.status.style_qt_label(text)
        layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(text, 1, Qt.AlignmentFlag.AlignTop)
        opacity = entry.status.opacity
        if opacity != 1.0:
            effect = QGraphicsOpacityEffect(row)
            effect.setOpacity(opacity)
            row.setGraphicsEffect(effect)
        return row

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method name
        self._drop_subscription()
        super().closeEvent(event)
