"""Qt team board — a modal dialog over the shared `TeamBoardState`.

Opened by `QtToadApp.open_team_board` (overrides the `ClientApplication` stub);
the hamburger menu's `TeamAction` fires that capability. Subscribes to
`TeamHudChanged` / `TeamHudFailed` on show and routes them through the shared
state owner, so Qt's filtered view matches Textual's `TeamPage` rendering for
the same frame.

Layout:
  - top: error label (hidden until a `TeamHudFailed` arrives)
  - middle: empty label ("Waiting for the team heartbeat.") until the first
    frame; once populated, a QTabWidget with one `QtTeamMemberView` per hud
  - bottom: Close button

Each `QtTeamMemberView` renders one teammate:
  - heading ("Team <name>") + status strip from `hud.status_strip(now)`
  - filter QLineEdit + "Needs hand" QCheckBox
  - QTreeWidget of sections → tables → records, using
    `TeamBoardState.filter_hud_sections` for the per-member filter (the SAME
    helper Textual's `TeamFrameView` uses).
"""

from __future__ import annotations

import time
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from agent_comms.team.team_hud import TeamHud
from toad.client.subscribers import CallbackSubscription
from toad.client.team_board import TeamBoardState
from toad.core.events import TeamHudChanged, TeamHudFailed
from toad.qt.core_events import QtCoreObserver
from toad.qt.metrics import UiGap
from toad.qt.presented_window import PresentedWindow
from toad.qt.window import QtToadApp

class QtTeamBoardScreen(PresentedWindow, QtCoreObserver, QDialog):
    """Modal team board dialog.

    `team_name` restricts the view to a single teammate (empty = show all),
    mirroring Textual's `TeamPage(teammate)` parameter. Both frontends pass
    this to `TeamBoardState.team_name_filter`, so the apply-side filter is
    one shared method — not a per-frontend branch."""

    def __init__(self, app: "QtToadApp", team_name: str = "") -> None:
        super().__init__()
        self.setParent(app)
        self.setWindowTitle("Team")
        self.resize(900, 650)
        self.app = app  # QtCoreObserver's AppScoped expects this
        self.state = TeamBoardState(team_name_filter=team_name)
        self.state.observe(self._state_changed)
        self._attached = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.setSpacing(UiGap.normal)

        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.empty_label = QLabel("Waiting for the team heartbeat.", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)

        self.tabs = QTabWidget(self)
        self.tabs.setVisible(False)
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @property
    def coordination(self):
        return self.app.coordination_access

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._attached:
            self._attached = True
            self.observe_core_callback(
                self.coordination.events, TeamHudChanged,
                self._on_hud_changed, factory=CallbackSubscription)
            self.observe_core_callback(
                self.coordination.events, TeamHudFailed,
                self._on_hud_failed, factory=CallbackSubscription)
            self.coordination.show_team(self, True, self.state.selection)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._attached:
            self.coordination.show_team(self, False, self.state.selection)
            self.close_core_events()
            self._attached = False
        super().closeEvent(event)

    def _on_hud_changed(self, event: TeamHudChanged) -> None:
        self.state.apply_hud_change(event.huds)

    def _on_hud_failed(self, event: TeamHudFailed) -> None:
        self.state.apply_hud_failure(event.error)

    def _state_changed(self) -> None:
        """TeamBoardState observer: rebuild tabs + error/empty visibility."""
        if self.state.last_error is not None:
            message = ' '.join(str(self.state.last_error).splitlines())
            self.error_label.setText(f"Team rows unavailable: {message}")
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)

        huds = self.state.huds
        self.empty_label.setVisible(not huds)
        self.tabs.setVisible(bool(huds))

        # Rebuild tabs in-place. Teams are small (few members); the heartbeat
        # doesn't fire often enough for incremental diffing to matter.
        self.tabs.clear()
        for hud in huds:
            tab = QtTeamMemberView(self.state, hud, self)
            self.tabs.addTab(tab, hud.teammate.name)


class QtTeamMemberView(QWidget):
    """One teammate's tab: heading + status + filter + "Needs hand" + groups tree.

    Reads `hud.status_strip(now)` for the status line, iterates
    `self.state.filter_hud_sections(self.hud, text, needs_hand)` for the
    displayed sections, and renders each as a QTreeWidget top-level node with
    the table rows as children. The SAME filter helper powers Textual's
    `TeamFrameView.filtered_sections`."""

    def __init__(self, state: TeamBoardState, hud: "TeamHud",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.hud = hud

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.normal, UiGap.normal, UiGap.normal, UiGap.normal)
        layout.setSpacing(UiGap.tight)

        self.heading = QLabel(f"Team {hud.teammate.name}", self)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        controls.setSpacing(UiGap.normal)
        self.filter_input = QLineEdit(self)
        self.filter_input.setPlaceholderText("Filter team records")
        self.filter_input.textChanged.connect(self._render)
        controls.addWidget(self.filter_input, 1)
        self.needs_hand_check = QCheckBox("Needs hand", self)
        self.needs_hand_check.stateChanged.connect(self._render)
        controls.addWidget(self.needs_hand_check)
        layout.addLayout(controls)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, 1)

        self._render()

    def _render(self) -> None:
        self.status.setText(self.hud.status_strip(time.time()))
        self.tree.clear()
        shown = self.state.filter_hud_sections(
            self.hud, self.filter_input.text(), self.needs_hand_check.isChecked())
        for group, section in shown.items():
            heading_item = QTreeWidgetItem([section.heading()])
            for table in section.tables:
                for record, cells in zip(table.records, table.texts):
                    row_text = " │ ".join(cells)
                    heading_item.addChild(QTreeWidgetItem([row_text]))
            self.tree.addTopLevelItem(heading_item)
            heading_item.setExpanded(True)
