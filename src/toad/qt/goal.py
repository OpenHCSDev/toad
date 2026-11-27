"""A direct message's goal on Qt: the TUI's goal bar, drawn with Qt widgets.

GoalBarOwner decides what the bar shows (state line, objective and progress, standby row,
and which GoalInteraction buttons are shown, enabled and captioned), and GoalControlsSession
owns how a press activates, how a write settles by reading the owner and how a refusal is
reported. Both are the Textual GoalBar's and GoalSession's parents. This module only draws
their answers; the TUI's GoalObservation reads the peer's goal into it over CommsGoalSource,
the owner path a viewer with no ACP session uses.
"""

from __future__ import annotations

from functools import partial
from weakref import ReferenceType, ref

from agent_comms.coordination.errors import Refused
from agent_comms.planning.goal_presentation import GoalExecutionControls, IdleGoalExecution
from agent_comms.planning.goals import NoGoal
from agent_comms.registry.thread_identity import ThreadIncarnation
from agent_comms.ui_model.goal import GoalDisplay
from formbridge.operations import OperationKind
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QDialogButtonBox,
    QHBoxLayout,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from toad.client.pending import ActionRunning, awaited
from toad.client.application import ClientApplication
from toad.client.connection import CoordinationAccess
from toad.client.goal_source import CommsGoalSource
from toad.client.line_blocks import MutedRole
from toad.client.subscribers import ThreadCallbackSubscription
from toad.goal_controls import (
    GoalBarOwner,
    GoalCollapse,
    GoalControlsSession,
    GoalHistoryPage,
    GoalInteraction,
    GoalInteractionControl,
    GoalPress,
)
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.session_observation import GoalObservation
from toad.core.events import ThreadRowsChanged
from toad.widget_contracts import DismissibleContract, SubmitsContract
from toad.qt.metrics import UiGap
from toad.qt.presented_window import PresentedWindow
from toad.qt.tap_flash import QtTextButton
from ui_theme.scheme import SecondaryColour


class QtGoalControl(QtTextButton, GoalInteractionControl, metaclass=PyQtWidgetMeta):
    """One GoalInteraction as a Qt text button; the family owns its label, state and press,
    and `QtTextButton` owns its flat themed style and 160 ms tap inversion."""

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
        return self.bar.goal_source

    def owns(self, binding: CommsGoalSource) -> bool:
        return self.bar.is_attached and self.bar.session is self and self.bar.goal_source is binding

    async def refresh(self, binding: CommsGoalSource) -> None:
        await self.bar.goal_observation.refresh()

    def report_unavailable(self, heading: str) -> None:
        self.host.show_info(heading, "Goal")

    def history_view(self, page: GoalHistoryPage) -> QtGoalHistory:
        return QtGoalHistory(self.bar, page)

    async def edit_view(self, goal, on_save) -> QtGoalEdit:
        return QtGoalEdit(self.bar, goal, on_save)

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


class QtGoalBar(QtCoreObserver, GoalBarOwner, GoalCollapse, QWidget, metaclass=PyQtWidgetMeta):
    """The peer's goal over the composer, as the TUI's goal bar sits over its prompt: a
    secondary rule on top (Textual's `GoalEdge`), the state line, the objective scrolled
    within a fifth of the window (Textual's `20vh` cap) and the action row."""

    document_share = 0.2

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer, peer: ThreadIncarnation) -> None:
        super().__init__()
        self.app, self.peer = app, peer
        self.goal_source = CommsGoalSource(app, peer, str(app.source().root))
        self.session = QtGoalSession(self)
        self.goal_observation = GoalObservation(self)
        self._goal_display: GoalDisplay = NoGoal()
        self._goal_execution: GoalExecutionControls = IdleGoalExecution()
        self.collapsed = False
        self.is_attached = False
        self.header = ElidedLine()
        self.standby = ElidedLine()
        self.objective = WrappedText()
        self.progress = WrappedText()
        # Parent self so the document stays a child from creation, not a top-level QWindow
        # on Qt-for-Android (prevents the EGL deadlock protector shape PR #1885 fixed).
        self.document = QScrollArea(self)
        self.document.setWidgetResizable(True)
        self.document.setFrameShape(QFrame.Shape.NoFrame)
        self.document.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(self.document)
        document = QVBoxLayout(body)
        document.setContentsMargins(0, 0, 0, 0)
        document.addWidget(self.objective)
        document.addWidget(self.progress)
        document.addStretch(1)
        self.document.setWidget(body)
        self.actions = tuple(QtGoalControl(interaction, self) for interaction in self.goal_interactions())
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(UiGap.frame)
        for control in self.actions:
            controls.addWidget(control)
        controls.addStretch(1)
        self.setObjectName("goal-bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        renderer.themed(self, partial(self.paint_colours, renderer))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.loose, UiGap.tight, UiGap.loose, UiGap.tight)
        layout.setSpacing(0)
        layout.addWidget(self.header)
        layout.addWidget(self.standby)
        layout.addWidget(self.document)
        layout.addLayout(controls)
        self.present_goal_document(self._goal_display)
        self.present_state()

    def paint_colours(self, renderer: QtLineRenderer) -> None:
        """The standby and progress lines muted, the controls and the bar's top border in the
        secondary colour, under the renderer's current scheme."""
        muted = renderer.color_style(MutedRole)
        secondary = renderer.theme(SecondaryColour)
        self.standby.setStyleSheet(muted)
        self.progress.setStyleSheet(muted)
        for control in self.actions:
            control.apply_text_style(renderer, SecondaryColour)
        self.setStyleSheet(f"#goal-bar {{ border-top: 1px solid {secondary} }}")

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

    def mount(self) -> None:
        """Start observing the thread's goal: called once from the view's mount, after the
        view's identity is bound, as `QtSessionDetails.mount` is. The bar hides itself until
        a goal is read, so it cannot wait for its own show event."""
        self.is_attached = True
        self.observe_core_callback(
            self.coordination.events, ThreadRowsChanged, self.rows_changed,
            factory=partial(ThreadCallbackSubscription, scope=(str(self.app.source().root), self.peer.name)))
        self.goal_observation.invalidate()

    def rows_changed(self, event: ThreadRowsChanged) -> None:
        self.goal_observation.invalidate()

    def present_state(self) -> None:
        self.present_goal_state(self.session, self.collapsed)

    def press(self, interaction: type[GoalInteraction]) -> None:
        self.app.run_operation(GoalPress, partial(self.session.activate, interaction))

    def close_activity(self) -> None:
        self.is_attached = False
        self.session.close()
        super().close_activity()
        self.app.run_operation(GoalPress, self.goal_observation.close)

    # GoalBarOwner's drawing hooks

    def show_goal(self, visible: bool) -> None:
        self.setVisible(visible)

    def show_goal_text(self, objective: str, progress: str, shows_progress: bool) -> None:
        self.objective.setText(objective)
        self.progress.setText(progress)
        self.progress.setVisible(shows_progress)
        self.fit_document()

    def fit_document(self) -> None:
        """The document is as tall as its wrapped text at the viewport width, up to its share
        of the window."""
        body = self.document.widget()
        width = self.document.viewport().width()
        if width <= 0:
            margins = self.layout().contentsMargins()
            width = max(0, self.width() - margins.left() - margins.right())
        content_height = (
            body.heightForWidth(width)
            if width > 0 and body.hasHeightForWidth()
            else body.sizeHint().height()
        )
        cap = int(QWidget.window(self).height() * self.document_share) or content_height
        self.document.setFixedHeight(max(1, min(content_height, cap)))

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.fit_document()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.fit_document()

    def show_heading(self, heading: str) -> None:
        self.header.setText(heading)

    def show_document(self, shown: bool) -> None:
        self.document.setVisible(shown)

    def show_standby(self, shown: bool) -> None:
        self.standby.setVisible(shown)

    def show_execution_text(self, text: str) -> None:
        self.standby.setText(text)


class QtGoalHistory(PresentedWindow, QDialog, DismissibleContract):
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


class QtGoalEdit(PresentedWindow, QDialog, DismissibleContract, SubmitsContract):
    """The goal's objective in an editor; Save writes it through the session's settle-by-read."""

    dismiss_control = QDialog.reject

    def submit(self) -> None:
        self.save()

    def __init__(self, bar: QtGoalBar, goal, on_save) -> None:
        super().__init__(bar.window())
        self.bar, self.goal, self.on_save = bar, goal, on_save
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

    def save(self) -> None:
        text = self.editor.toPlainText().strip()
        if text:
            self.bar.app.run_operation(GoalPress, partial(self.write, text))

    async def write(self, text: str) -> None:
        try:
            await self.on_save(text)
        except Refused as error:
            self.error.setText(str(error))
            return
        self.accept()
