"""A direct message's goal on Qt: the TUI's goal bar, drawn with Qt widgets.

GoalBarOwner decides what the bar shows (state line, objective and progress, standby row,
and which GoalInteraction buttons are shown, enabled and captioned), and GoalControlsSession
owns how a press activates, how a write settles by reading the owner and how a refusal is
reported. Both are the Textual GoalBar's and GoalSession's parents. This module only draws
their answers; the TUI's GoalObservation reads the peer's goal into it over CommsGoalSource,
the owner path a viewer with no ACP session uses.
"""

from __future__ import annotations

from collections.abc import Awaitable
from functools import partial
from typing import Any
from weakref import ReferenceType, ref

from agent_comms.coordination.errors import Refused
from agent_comms.planning.goal_actions import GoalAction
from agent_comms.planning.goal_history import RecordedGoalHistory
from agent_comms.planning.goal_presentation import GoalExecutionControls, IdleGoalExecution
from agent_comms.planning.goals import Goal, NoGoal
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.goal import GoalDisplay
from formbridge.operations import OperationKind
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPlainTextEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.client.goal_source import CommsGoalSource
from toad.client.line_blocks import MutedRole
from toad.client.subscribers import ThreadCallbackSubscription
from toad.goal_controls import (
    GoalBarOwner,
    GoalControlsSession,
    GoalHistoryPage,
    GoalInteraction,
    GoalInteractionControl,
)
from toad.qt.core_events import QtCoreObserver
from toad.qt.host import ScreenWideWindow
from toad.qt.lines import QtLineRenderer
from toad.session_observation import GoalObservation
from toad.core.events import ThreadRowsChanged
from toad.widget_contracts import DismissibleContract, SubmitsContract
from toad.qt.metrics import UiGap


class GoalPress(OperationKind):
    """One goal button press: read the owner, then apply the button."""


class QtGoalControl(QToolButton, GoalInteractionControl, metaclass=PyQtWidgetMeta):
    """One GoalInteraction as a Qt button; the family owns its label, state and press."""

    def __init__(self, interaction: type[GoalInteraction], bar: QtGoalBar) -> None:
        super().__init__()
        self.interaction = interaction
        self.setText(interaction.label)
        self.setAutoRaise(True)
        self.setMinimumHeight(36)
        self.clicked.connect(partial(bar.press, interaction))

    def set_shown(self, shown: bool) -> None:
        self.setVisible(shown)

    def set_label(self, label: str) -> None:
        self.setText(label)

    def set_enabled(self, enabled: bool) -> None:
        self.setEnabled(enabled)


class QtGoalSession(GoalControlsSession[CommsGoalSource]):
    """The Qt goal controls, bound to the peer's comms goal source. The base owns the
    `change`/`open_history` envelopes; only the backend-specific hooks live here."""

    def __init__(self, bar: QtGoalBar) -> None:
        self.bar = bar
        self._open_dialog: ReferenceType[QDialog] | None = None

    @property
    def display(self) -> GoalDisplay:
        return self.bar.goal_display

    @property
    def execution(self) -> GoalExecutionControls:
        return self.bar.goal_execution

    @property
    def host(self) -> ClientApplication:
        return self.bar.app

    @property
    def binding(self) -> CommsGoalSource:
        return self.bar.agent_binding

    def owns(self, binding: CommsGoalSource) -> bool:
        return self.bar.is_attached and self.bar.session is self and self.bar.agent_binding is binding

    async def refresh(self, binding: CommsGoalSource) -> None:
        await self.bar.goal_observation.refresh()

    def apply_goal_change(
        self, binding: CommsGoalSource, action: type[GoalAction], goal: Goal, text: str
    ) -> Awaitable[Any]:
        return binding.act(action, goal)

    def unavailable(self) -> None:
        self.host.show_info(self.display.heading(self.execution), "Goal")

    async def read_goal_history(self, binding: CommsGoalSource, goal: Goal) -> RecordedGoalHistory:
        return await binding.history(goal)

    def show_history(self, binding: CommsGoalSource, page: GoalHistoryPage) -> None:
        self.present(QtGoalHistory(self.bar, page))

    async def open_edit(self) -> None:
        self.present(QtGoalEdit(self.bar, self, self.display.snapshot.require()))

    def present(self, dialog: QDialog) -> None:
        """Replace whatever this session was showing with `dialog` and open it. Tracking the
        reference lets `close()` dismiss whichever view is current without the frontends
        needing their own open-dialog bookkeeping."""
        self.close()
        self._open_dialog = ref(dialog)
        dialog.open()

    def close(self) -> None:
        dialog = self._open_dialog() if self._open_dialog is not None else None
        if dialog is not None and dialog.isVisible():
            dialog.reject()
        self._open_dialog = None

    def toggle_collapsed(self) -> None:
        self.bar.collapsed = not self.bar.collapsed
        self.bar.present_state()


class QtGoalBar(QtCoreObserver, GoalBarOwner, QWidget, metaclass=PyQtWidgetMeta):
    """The peer's goal over the composer, as the TUI's goal bar sits over its prompt."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, peer: ThreadIncarnation) -> None:
        super().__init__()
        self.app, self.peer = app, peer
        self.agent_binding = CommsGoalSource(app, peer)
        self.session = QtGoalSession(self)
        self.goal_observation = GoalObservation(self)
        self._goal_display: GoalDisplay = NoGoal()
        self._goal_execution: GoalExecutionControls = IdleGoalExecution()
        self.collapsed = False
        self.is_attached = False
        muted = renderer.color_style(MutedRole)
        self.header = ElidedLine()
        self.standby = ElidedLine()
        self.standby.setStyleSheet(muted)
        self.objective = WrappedText()
        self.progress = WrappedText()
        self.progress.setStyleSheet(muted)
        # Parent self so the document stays a child from creation, not a top-level QWindow
        # on Qt-for-Android (prevents the EGL deadlock protector shape PR #1885 fixed).
        self.document = QWidget(self)
        document = QVBoxLayout(self.document)
        document.setContentsMargins(0, 0, 0, 0)
        document.addWidget(self.objective)
        document.addWidget(self.progress)
        self.actions = tuple(QtGoalControl(interaction, self) for interaction in self.goal_interactions())
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        for control in self.actions:
            controls.addWidget(control)
        controls.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.loose, UiGap.tight, UiGap.loose, UiGap.tight)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.standby)
        layout.addWidget(self.document)
        layout.addLayout(controls)
        self.present_goal_document(self._goal_display)
        self.present_state()

    @property
    def coordination(self) -> CoordinationAccess:
        return self.app.coordination_access

    # What GoalObservation reads into and publishes, as it does for the TUI's conversation

    @property
    def goal_display(self) -> GoalDisplay:
        return self._goal_display

    @goal_display.setter
    def goal_display(self, display: GoalDisplay) -> None:
        if display != self._goal_display:
            self._goal_display = display
            self.present_goal_document(display)
        self.present_state()

    @property
    def goal_execution(self) -> GoalExecutionControls:
        return self._goal_execution

    @goal_execution.setter
    def goal_execution(self, execution: GoalExecutionControls) -> None:
        self._goal_execution = execution
        self.present_state()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._attach_observation_if_needed()

    def _attach_observation_if_needed(self) -> None:
        """Subscribe the core-event callback + fire the first observation. Must
        NOT be gated on showEvent: ``present_state()`` in ``__init__`` sets
        ``show_goal(False)`` when no goal snapshot has been read yet, which
        hides the widget — if observation only started in ``showEvent``, the
        widget would never become visible and the observation would never fire.
        Called from both ``showEvent`` (for the normal path) AND externally by
        the parent view right after mount, so an unset-on-construction goal
        still gets its first read."""
        if self.is_attached:
            return
        self.is_attached = True
        self.observe_core_callback(
            self.coordination.events, ThreadRowsChanged, self.rows_changed,
            factory=partial(ThreadCallbackSubscription, scope=(str(self.app.source().root), self.peer.name)))
        self.goal_observation.invalidate()

    def rows_changed(self, event: ThreadRowsChanged) -> None:
        self.goal_observation.invalidate()
        # Piggyback: a ThreadRowsChanged event for this peer also implies the
        # remote thread's status/is_working/model_info may have changed —
        # refresh the sibling composer-surround lines so the thinking + status
        # indicators update without each widget needing its own subscription.
        # The parent view owns the lines; we find it via Qt parent chain and
        # call its refresh hook if it has one.
        view = self.parentWidget()
        while view is not None and not hasattr(view, "refresh_composer_surround"):
            view = view.parentWidget()
        if view is not None:
            try:
                view.refresh_composer_surround()
            except Exception as error:
                print(
                    f"QtGoalBar refresh_composer_surround failed: {error!r}",
                    flush=True,
                )

    def present_state(self) -> None:
        self.present_goal_state(self.session, self.collapsed)

    def press(self, interaction: type[GoalInteraction]) -> None:
        self.app.run_operation(GoalPress, partial(self.session.activate, interaction))

    def close_activity(self) -> None:
        self.is_attached = False
        self.session.close()
        self.close_core_events()
        self.app.run_operation(GoalPress, self.goal_observation.close)

    # GoalBarOwner's drawing hooks

    def show_goal(self, visible: bool) -> None:
        self.setVisible(visible)

    def show_goal_text(self, objective: str, progress: str, shows_progress: bool) -> None:
        self.objective.setText(objective)
        self.progress.setText(progress)
        self.progress.setVisible(shows_progress)

    def show_heading(self, heading: str) -> None:
        self.header.setText(heading)

    def show_document(self, shown: bool) -> None:
        self.document.setVisible(shown)

    def show_standby(self, shown: bool) -> None:
        self.standby.setVisible(shown)

    def show_execution_text(self, text: str) -> None:
        self.standby.setText(text)


class QtGoalHistory(ScreenWideWindow, QDialog, DismissibleContract):
    """The goal's revisions and failed attempts, listed as the TUI's GoalDetails lists them."""

    dismiss_control = QDialog.reject

    def __init__(self, bar: QtGoalBar, page: GoalHistoryPage) -> None:
        super().__init__(bar.window())
        self.setWindowTitle("Goal history")
        body = QWidget(self)
        lines = QVBoxLayout(body)
        lines.addWidget(WrappedText("Revision history"))
        for revision in page.revisions():
            lines.addWidget(WrappedText(revision.heading))
            for text in revision.texts:
                lines.addWidget(WrappedText(text))
        failures = tuple(page.failures())
        if failures:
            lines.addWidget(WrappedText("Failed attempts"))
            for failure in failures:
                lines.addWidget(WrappedText(failure))
        lines.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        self.fit_screen()


class QtGoalEdit(ScreenWideWindow, QDialog, DismissibleContract, SubmitsContract):
    """The goal's objective in an editor; Save writes it through the session's settle-by-read."""

    dismiss_control = QDialog.reject

    def submit(self) -> None:
        self.save()

    def __init__(self, bar: QtGoalBar, session: QtGoalSession, goal) -> None:
        super().__init__(bar.window())
        self.bar, self.session, self.goal = bar, session, goal
        self.setWindowTitle("Edit objective")
        self.editor = QPlainTextEdit(goal.text)
        self.error = WrappedText()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor, 1)
        if goal.progress:
            layout.addWidget(WrappedText(f"Progress (read-only): {goal.progress}"))
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.fit_screen()

    def save(self) -> None:
        text = self.editor.toPlainText().strip()
        if text:
            self.bar.app.run_operation(GoalPress, partial(self.write, text))

    async def write(self, text: str) -> None:
        source = self.session.binding
        try:
            await self.session.write(source, source.edit(self.goal, text))
        except Refused as error:
            self.error.setText(str(error))
            return
        self.accept()
