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
  - heading ("Board for <name>") + status strip from `hud.status_strip(now)`
  - filter QLineEdit + "Needs hand" QCheckBox
  - QTreeWidget of sections → tables → records, using
    `TeamBoardState.filter_hud_sections` for the per-member filter (the SAME
    helper Textual's `TeamFrameView` uses).
"""

from __future__ import annotations

import asyncio
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
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from agent_comms.team.board_actions import BoardActionOffer
from agent_comms.team.team_hud import TeamBoardCut, TeamHud
from agent_comms.transport.request import CoreAccess
from toad.client.subscribers import CallbackSubscription
from toad.client.team_board import TeamBoardState, TeamMemberBoard
from toad.core.events import TeamHudChanged, TeamHudFailed
from toad.qt.core_events import QtCoreObserver
from toad.qt.metrics import UiGap
from toad.qt.presented_window import PresentedWindow
from toad.qt.window import QtToadApp
from toad.target_commands import BoardCommand

class QtTeamBoardScreen(PresentedWindow, QtCoreObserver, QDialog):
    """Modal team board dialog.

    `team_name` restricts the view to a single teammate (empty = show all),
    mirroring Textual's `TeamPage(teammate)` parameter. Both frontends pass
    this to `TeamBoardState.team_name_filter`, so the apply-side filter is
    one shared method — not a per-frontend branch."""

    def __init__(self, app: QtToadApp, team_name: str = "") -> None:
        self.members = {}
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
        TeamBoardState.apply_update(self.state, event.cut)

    def _on_hud_failed(self, event: TeamHudFailed) -> None:
        self.state.apply_hud_failure(event.error)

    def _state_changed(self, cut: TeamBoardCut | None) -> None:
        """Reconcile only identities named by Core's atomic publication."""
        if self.state.last_error is not None:
            message = " ".join(str(self.state.last_error).splitlines())
            self.error_label.setText(f"Team rows unavailable: {message}")
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)
        huds = {hud.teammate: hud for hud in self.state.huds}
        self.empty_label.setVisible(not huds)
        self.tabs.setVisible(bool(huds))
        current = self.tabs.currentWidget()
        for key in tuple(self.members):
            if key in huds:
                continue
            view = self.members.pop(key)
            index = self.tabs.indexOf(view)
            if index >= 0:
                self.tabs.removeTab(index)
            view.deleteLater()
        changed = cut.changed if cut is not None else frozenset()
        for index, (key, hud) in enumerate(huds.items()):
            view = self.members.get(key)
            if view is None:
                view = QtTeamMemberView(
                    self.state, hud, self.coordination.open_current().core, self.app.preparation, self,
                )
                self.members[key] = view
                self.tabs.insertTab(index, view, hud.teammate.name)
            else:
                if key in changed:
                    view.present(hud)
                existing = self.tabs.indexOf(view)
                if existing != index:
                    self.tabs.removeTab(existing)
                    self.tabs.insertTab(index, view, hud.teammate.name)
                else:
                    self.tabs.setTabText(index, hud.teammate.name)
        if current is not None and self.tabs.indexOf(current) >= 0:
            self.tabs.setCurrentWidget(current)


class QtTeamMemberView(TeamMemberBoard, QWidget):
    """One teammate's tab: heading + status + filter + "Needs hand" + groups tree.

    Reads `hud.status_strip(now)` for the status line, iterates
    `self.state.filter_hud_sections(self.hud, text, needs_hand)` for the
    displayed sections, and renders each as a QTreeWidget top-level node with
    the table rows as children. The SAME filter helper powers Textual's
    `TeamFrameView.filtered_sections`."""

    def present(self, hud: TeamHud) -> None:
        self.hud = hud
        self._render()

    def __init__(self, state: TeamBoardState, hud: TeamHud, core: CoreAccess, preparation,
                 parent: QWidget | None = None) -> None:
        self.groups = {}
        self.rows = {}
        self.action_buttons: dict[BoardActionOffer, QPushButton] = {}
        super().__init__(parent)
        self.state = state
        self.hud = hud
        self.core = core
        self.preparation = preparation

        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.normal, UiGap.normal, UiGap.normal, UiGap.normal)
        layout.setSpacing(UiGap.tight)

        self.heading = QLabel(f"Board for {hud.teammate.name}", self)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(UiGap.tight)
        layout.addLayout(self.actions)

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

    def _apply_board_command(self, command: BoardCommand, _checked: bool = False) -> None:
        asyncio.ensure_future(self._run_board_command(command))

    async def _run_board_command(self, command: BoardCommand) -> None:
        try:
            result = await self.preparation.run_thread(command.execute, self.core)
        except Exception as error:
            self.status.setText(str(error))
            return
        self.status.setText("\n".join(result.lines))

    def _render_actions(self) -> None:
        commands = {command.offer: command for command in BoardCommand.for_hud(self.hud)}
        for offer in tuple(self.action_buttons):
            if offer in commands:
                continue
            button = self.action_buttons.pop(offer)
            self.actions.removeWidget(button)
            button.deleteLater()
        for offer, command in commands.items():
            if offer in self.action_buttons:
                continue
            button = QPushButton(command.label, self)
            button.clicked.connect(partial(self._apply_board_command, command))
            self.action_buttons[offer] = button
            self.actions.addWidget(button)

    def _render(self) -> None:
        self.status.setText(self.hud.status_strip(time.time()))
        self._render_actions()
        shown = self.filtered_sections_for(
            self.filter_input.text(), self.needs_hand_check.isChecked())
        for group in tuple(self.groups):
            if group in shown:
                continue
            item = self.groups.pop(group)
            index = self.tree.indexOfTopLevelItem(item)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            for key in tuple(self.rows):
                if key[0] is group:
                    del self.rows[key]
        for group_index, (group, section) in enumerate(shown.items()):
            heading = self.groups.get(group)
            if heading is None:
                heading = QTreeWidgetItem([section.heading()])
                self.groups[group] = heading
                self.tree.insertTopLevelItem(group_index, heading)
                heading.setExpanded(True)
            else:
                heading.setText(0, section.heading())
                existing = self.tree.indexOfTopLevelItem(heading)
                if existing != group_index:
                    self.tree.takeTopLevelItem(existing)
                    self.tree.insertTopLevelItem(group_index, heading)
            desired = [((group, key), " │ ".join(cells)) for table in section.tables
                       for (key, _record), cells in zip(table.entities.items(), table.texts)]
            desired_keys = {key for key, _text in desired}
            for key in tuple(self.rows):
                if key[0] is not group or key in desired_keys:
                    continue
                row = self.rows.pop(key)
                existing = heading.indexOfChild(row)
                if existing >= 0:
                    heading.takeChild(existing)
            for row_index, (key, text) in enumerate(desired):
                row = self.rows.get(key)
                if row is None:
                    row = QTreeWidgetItem([text])
                    self.rows[key] = row
                    heading.insertChild(row_index, row)
                else:
                    row.setText(0, text)
                    existing = heading.indexOfChild(row)
                    if existing != row_index:
                        heading.takeChild(existing)
                        heading.insertChild(row_index, row)
