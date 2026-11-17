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

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from toad.core import events as core_events
from toad.plan import PlanItem


class QtPlan(QWidget):
    spec_key: ClassVar[str] = "plan"
    """Which `ThreadSidebarPanelSpec.key` this widget renders — mirrors the TUI
    `SessionPanel.spec_key` convention so both frontends share one identity per panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(8, 4, 8, 8)
        self._column.setSpacing(2)
        self._column.addStretch(1)
        self._view = None
        self._subscription = None
        self._render()

    def bind(self, view) -> None:
        """Follow a new agent view: unsubscribe the old agent's Plan events and
        subscribe to future Plan updates on the new agent's event bus. Entries are
        read fresh from `controller.plan_display` on each render — no local cache."""
        self._drop_subscription()
        self._view = view
        agent = view.bound_agent if view is not None else None
        self._render()
        if agent is not None:
            self._subscription = agent.events.subscribe(core_events.Plan, self._on_plan)

    def _on_plan(self, event: core_events.Plan, subscription: object) -> None:
        self._render()

    def _drop_subscription(self) -> None:
        if self._subscription is None:
            return
        for name in ("close", "unsubscribe", "cancel"):
            method = getattr(self._subscription, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                break
        self._subscription = None

    def _clear_rows(self) -> None:
        # Keep the final addStretch(1) anchor at the end of the column.
        while self._column.count() > 1:
            item = self._column.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render(self) -> None:
        self._clear_rows()
        agent = self._view.bound_agent if self._view is not None else None
        entries = list(agent.controller.plan_display.entries) if agent is not None else []
        if not entries:
            empty = QLabel("No plan yet", self)
            font = empty.font()
            font.setItalic(True)
            empty.setFont(font)
            empty.setEnabled(False)  # dim via the palette's disabled text role
            self._column.insertWidget(0, empty)
            return
        for index, entry in enumerate(entries):
            row = self._build_row(entry)
            self._column.insertWidget(index, row)

    def _build_row(self, entry: PlanItem) -> QWidget:
        row = QWidget(self)
        row.setWindowFlags(Qt.WindowType.Widget)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        marker = QLabel(entry.status.marker(), row)
        text = QLabel(entry.content, row)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if entry.status.complete:
            font = text.font()
            font.setStrikeOut(True)
            text.setFont(font)
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
