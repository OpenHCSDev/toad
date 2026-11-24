"""Qt rendering of the coordination status panel.

Reads the same `CoordinationStateReport` that Textual's `CoordinationStatus` reads
(`toad.client.coordination_panel.read_coordination_state`); renders it with a Qt label and
a tooltip. One fact owner, two renderers.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta

from toad.thread_sidebar_declarations import CoordinationSidebarPanel, ThreadSidebarPanelBody
from toad.client.coordination_panel import CoordinationStateReport, CoordinationStatusView
from toad.thread_identity import NoThreadIdentity
from toad.qt.metrics import UiGap


class QtCoordinationStatus(CoordinationStatusView, ThreadSidebarPanelBody, QWidget, metaclass=PyQtWidgetMeta):
    panel_type = CoordinationSidebarPanel

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
        self.identity_changed(NoThreadIdentity())

    def show_report(self, report: CoordinationStateReport) -> None:
        self._label.setText(report.summary_text())
        self.setToolTip(report.tooltip_text())
