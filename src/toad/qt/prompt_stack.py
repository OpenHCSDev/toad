"""The rows under a Qt thread view's transcript, painted from `toad.client.prompt_stack`.

Each class inherits the parent its Textual sibling inherits and adds only Qt paint:
`QtFlash` ↔ `Flash` (`FlashNotice`), `QtSessionDetails` ↔ `SessionDetails`
(`ObservedActivity`, `SessionStatusTitle`), `QtStatusLine`/`QtInfoBar` ↔ `StatusLine`/
`InfoBar` (`SettingVisible`), `QtEditingModeBadge` ↔ `EditingModeLabel` (`EditingModeBadge`).
"""

from __future__ import annotations

import asyncio

from agent_comms.acp_extension import TurnChangedUpdate
from agent_comms.ui_model.delivery import DeliveryView
from agent_comms.ui_model.status import ThreadStatusModel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText
from ui_theme.scheme import AccentColour, BackgroundColour, SecondaryColour

from toad.client.line_blocks import FailureRole, MutedRole
from toad.client.prompt_stack import (
    DeliveryDetailsPage,
    EditingModeBadge,
    FlashNotice,
    FlashTone,
    SessionStatusTitle,
    SettingVisible,
)
from toad.client.session_history_details import SessionHistoryDetails
from toad.client.subscribers import CallbackSubscription
from toad.private_native_cursor import HiddenCursorStatus
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap
from toad.status_thread import ObservedActivity


class QtFlash(FlashNotice, ElidedLine, metaclass=PyQtWidgetMeta):
    """The centred transient notice, tinted by its tone over the transcript background."""

    def __init__(self, app, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.app, self.renderer = app, renderer
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide_flash)
        self.hide()

    @property
    def settings(self):
        return self.app.settings

    def show_flash(self, content, tone: type[FlashTone]) -> None:
        scheme = self.renderer.scheme
        ink = tone.colour.rgb(scheme)
        tint = BackgroundColour.rgb(scheme).blend(ink, 0.1)
        self.setStyleSheet(f"color: {ink.hex}; background: {tint.hex}")
        self.setText(str(content))
        self.show()

    def hide_flash(self) -> None:
        self.hide()

    def stop_flash_timer(self) -> None:
        self.timer.stop()

    def start_flash_timer(self, seconds: float) -> None:
        self.timer.start(int(seconds * 1000))


class QtSessionDetails(ObservedActivity, SessionStatusTitle, QtCoreObserver, QWidget, metaclass=PyQtWidgetMeta):
    """The collapsed session-status line (``▶ Thinking · …``) over its disclosed details.

    The view's status thread binds the observed row into it, as Textual's
    `OperationalSessionDetails`; a row or turn change asks the view to sync its working
    answer, which repaints this title and the sweep."""

    collapsed_symbol, expanded_symbol = "▶", "▼"
    # Textual's `NativeHistory.status`: a Qt client has no private native cursor, so the
    # saved-history status is hidden and `SessionHistoryDetails` reads only the coverage.
    status = HiddenCursorStatus
    display = HiddenCursorStatus.visible

    def __init__(self, view, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.view, self.app, self.renderer = view, view.app, renderer
        self.row = ThreadStatusModel.pending("")
        self.is_mounted = False
        self.expanded = False
        self.history_details = SessionHistoryDetails(view.transcript, self)
        self.title = QToolButton(self)
        self.title.setAutoRaise(True)
        self.title.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.title.clicked.connect(self.toggle)
        self.details = WrappedText()
        self.details.setStyleSheet(renderer.color_style(MutedRole))
        self.details.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        self.details.hide()
        # Textual's `InspectSession` detail action: underlined accent text in the disclosure.
        self.inspect_action = QToolButton(self)
        self.inspect_action.setText(self.inspect_label)
        self.inspect_action.setAutoRaise(True)
        self.inspect_action.setStyleSheet(
            f"QToolButton {{ color: {renderer.theme(AccentColour)}; text-decoration: underline; border: none }}")
        self.inspect_action.clicked.connect(lambda: asyncio.ensure_future(self.inspect()))
        self.inspect_action.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(self.inspect_action, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details)
        self.hide()

    @property
    def coordination(self):
        return self.app.coordination_access

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.mount()

    def mount(self) -> None:
        """Observe the bound thread and the turn once; Qt has no mount event, so the view
        calls this when it composes the row (a hidden row never gets a showEvent)."""
        if self.is_mounted:
            return
        self.is_mounted = True
        self.observe_core_callback(
            self.coordination.events, TurnChangedUpdate, self.turn_changed, factory=CallbackSubscription)
        self.start_observing()

    def turn_changed(self, event: TurnChangedUpdate) -> None:
        self.view.turns.bound()

    def show(self, row: ThreadStatusModel) -> None:  # type: ignore[override]
        """A new observed row: the view syncs its working answer and, as Textual's
        `thread_presented` does on every presented change, reads its status again."""
        self.row = row
        self.view.sync_working()
        self.view.present_thread_status()

    def refresh_summary(self) -> None:
        row = self.row
        title = self.summary_title(row, self.history_details.summary, DeliveryView())
        symbol = self.expanded_symbol if self.expanded else self.collapsed_symbol
        self.title.setText(f"{symbol} {title}")
        self.title.setStyleSheet(
            f"QToolButton {{ {self.renderer.color_style(self.title_role_for(row, self.status))};"
            " border: none; text-align: left; padding: 0 4px }")
        detail = self.detail_text(row)
        self.details.setText(detail)
        self.details.setVisible(self.expanded and bool(detail))
        self.inspect_action.setVisible(self.expanded)
        self.setVisible(self.shown(row))

    async def inspect(self) -> None:
        """This row holds its view, as Textual's `OperationalSessionDetails` holds its
        conversation, so it never asks the widget tree which one it is."""
        self.view.inspect_session()

    def overview(self) -> str:
        return self.history_details.overview(self.row.lines)

    def toggle(self) -> None:
        self.expanded = not self.expanded
        self.refresh_summary()

    def close_activity(self) -> None:
        self.close_core_events()


class QtInputDeliveryDetails(DeliveryDetailsPage, QDialog, metaclass=PyQtWidgetMeta):
    """Textual's `InputDeliveryDetails` as a dialog; `DeliveryDetailsPage` owns its text.

    A Qt thread view has no input-delivery observation, so the delivery is the view's
    `DeliveryView` answer and there are no earlier notices to load or clear."""

    def __init__(self, parent: QWidget, renderer: QtLineRenderer, overview: str,
                 delivery: DeliveryView) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.details_title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(UiGap.dialog, UiGap.dialog, UiGap.dialog, UiGap.dialog)
        layout.addWidget(WrappedText(self.details_title))
        error = WrappedText(self.error_text(delivery, ""))
        error.setStyleSheet(renderer.color_style(FailureRole))
        error.setVisible(bool(error.text()))
        layout.addWidget(error)
        body = WrappedText(overview)
        body.setVisible(bool(overview))
        layout.addWidget(body, 1)
        pending = WrappedText(self.pending_explanation)
        pending.setVisible(bool(delivery.current))
        layout.addWidget(pending)
        layout.addWidget(WrappedText(delivery.pending_records_text()))
        layout.addWidget(WrappedText(delivery.history_summary))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class QtStatusLine(SettingVisible, ElidedLine, setting="ui.status_line", metaclass=PyQtWidgetMeta):
    """The info bar's status, right-aligned in the secondary ink, as Textual's `StatusLine`."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setStyleSheet(f"color: {renderer.theme(SecondaryColour)}")

    def present_status(self, status) -> None:
        text = str(status)
        self.setText(text)
        self.setToolTip(text)


class QtEditingModeBadge(EditingModeBadge, QLabel, metaclass=PyQtWidgetMeta):
    """The editing mode in reverse video at the info bar's right edge."""

    def __init__(self, renderer: QtLineRenderer) -> None:
        super().__init__()
        scheme = renderer.scheme
        self.setStyleSheet(
            f"color: {BackgroundColour.rgb(scheme).hex}; background: {renderer.theme(SecondaryColour)};"
            " padding: 0 4px")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def show_mode_label(self, label: str) -> None:
        self.setText(label)


class QtInfoBar(SettingVisible, QWidget, setting="ui.info_bar", metaclass=PyQtWidgetMeta):
    """Under the prompt frame: the composer's directory (a CLI thread's), the status line and
    the editing-mode badge, in Textual's `InfoBar` order."""

    def __init__(self, app, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.path = ElidedLine()
        self.path.setStyleSheet(f"color: {renderer.theme(SecondaryColour)}")
        self.path.hide()
        self.status = QtStatusLine(renderer)
        self.badge = QtEditingModeBadge(renderer)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(UiGap.frame, 0, UiGap.frame, UiGap.tight)
        layout.setSpacing(UiGap.loose)
        layout.addWidget(self.path, 1)
        # Without a path (a message prompt) the free space sits left of the status, so the
        # status and badge keep to the right edge as Textual docks them.
        layout.addStretch(0)
        layout.addWidget(self.status)
        layout.addWidget(self.badge)
        state = app.configuration_state
        self.setVisible(self.setting_visible(state))
        self.status.setVisible(self.status.setting_visible(state))

    def show_path(self, path: str) -> None:
        self.path.setText(path)
        self.path.setToolTip(path)
        self.path.setVisible(bool(path))
