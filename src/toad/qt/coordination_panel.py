"""Qt rendering of the coordination status panel.

Reads the same `CoordinationStateReport` that Textual's `CoordinationStatus` reads
(`toad.client.coordination_panel.read_coordination_state`); renders it with a Qt label and
a tooltip. One fact owner, two renderers.
"""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from toad.client.coordination_panel import read_coordination_state
from toad.thread_identity import NoThreadIdentity, SessionIdentity
from toad.qt.metrics import UiGap


class QtCoordinationStatus(QWidget):
    spec_key: ClassVar[str] = "coordination"
    """Which `ThreadSidebarPanelSpec.key` this widget renders — matches the TUI
    `SessionPanel.spec_key` convention so both frontends declare the same identity."""

    """Compact 3-line summary of the coordination wire's identity and the ACP backend."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.frame, UiGap.normal, UiGap.frame, UiGap.frame)
        layout.setSpacing(0)
        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label)
        self.apply(NoThreadIdentity())

    def apply(self, identity: SessionIdentity) -> None:
        report = read_coordination_state(identity)
        self._label.setText(report.summary_text())
        self.setToolTip(report.tooltip_text())
