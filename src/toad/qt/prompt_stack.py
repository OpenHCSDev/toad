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
    SessionStatusTitle,
    SettingVisible,
)
from toad.client.view_settings import SettingsReading
from toad.flash_host import FlashNotice, FlashTone
from toad.key_modes import Standard
from toad.client.session_history_details import SessionHistoryDetails
from toad.client.subscribers import CallbackSubscription
from toad.private_native_cursor import HiddenCursorStatus
from toad.qt.core_events import QtCoreObserver
from toad.qt.lines import QtLineRenderer
from toad.qt.metrics import UiGap
from toad.qt.tap_flash import QtTextButton
from toad.status_thread import ObservedActivity
from toad.qt.presented_window import PresentedWindow


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

    def show_flash(self, content, tone: type[FlashTone]) -> None:
        scheme = self.renderer.scheme
        ink = tone.colour.rgb(scheme)
        tint = BackgroundColour.rgb(scheme).blend(ink, 0.1)
        self.renderer.apply_sheet(self, f"color: {ink.hex}; background: {tint.hex}")
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
        self.title = QtTextButton(self)
        self.title.setAutoRaise(True)
        self.title.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.title.clicked.connect(self.toggle)
        self.details = WrappedText()
        self.details.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        self.details.hide()
        # Textual's `InspectSession` detail action: underlined accent text in the disclosure.
        self.inspect_action = QtTextButton(self)
        self.inspect_action.setText(self.inspect_label)
        self.inspect_action.setAutoRaise(True)
        self.inspect_action.clicked.connect(lambda: asyncio.ensure_future(self.inspect()))
        self.inspect_action.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(self.inspect_action, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.details)
        renderer.themed(self, self.paint_colours)
        self.hide()

    def paint_colours(self) -> None:
        """The muted details, the accent inspect action and the title in its status role,
        under the renderer's current scheme."""
        self.details.setStyleSheet(self.renderer.color_style(MutedRole))
        self.inspect_action.apply_text_style(self.renderer, AccentColour, underline=True)
        self.paint_title()

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

    def paint_title(self) -> None:
        """The title in its row's status role, under the renderer's current scheme."""
        role = self.title_role_for(self.row, self.status)
        self.title.apply_text_style(self.renderer, role.colour, left_align=True, pad_x=4)

    def refresh_summary(self) -> None:
        row = self.row
        title = self.summary_title(row, self.history_details.summary, DeliveryView())
        symbol = self.expanded_symbol if self.expanded else self.collapsed_symbol
        self.title.setText(f"{symbol} {title}")
        self.paint_title()
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


class QtInputDeliveryDetails(PresentedWindow, DeliveryDetailsPage, QDialog, metaclass=PyQtWidgetMeta):
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
        # Each line joins the layout (and so gets its parent) before its visibility is set: a
        # parentless widget made visible becomes its own top-level window, which deadlocks
        # Android's accessibility bridge against its EGL surface (SIGABRT).
        error = WrappedText(self.error_text(delivery, ""))
        layout.addWidget(error)
        renderer.themed(error, lambda: error.setStyleSheet(renderer.color_style(FailureRole)))
        error.setVisible(bool(error.text()))
        body = WrappedText(overview)
        layout.addWidget(body, 1)
        body.setVisible(bool(overview))
        pending = WrappedText(self.pending_explanation)
        layout.addWidget(pending)
        pending.setVisible(bool(delivery.current))
        layout.addWidget(WrappedText(delivery.pending_records_text()))
        layout.addWidget(WrappedText(delivery.history_summary))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class QtSettingVisibility(SettingVisible, SettingsReading):
    """A Qt row the shared `SettingVisible` setting shows when the row is shown, as Textual's
    `SettingVisibility` applies it on mount. The row is handed the view it sits in."""

    def show_setting(self, visible: bool) -> None:
        if self.isHidden() == visible:
            self.setVisible(visible)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.apply_setting_visibility()


class QtStatusLine(QtSettingVisibility, ElidedLine, setting="ui.status_line", metaclass=PyQtWidgetMeta):
    """The info bar's status, right-aligned in the secondary ink, as Textual's `StatusLine`."""

    def __init__(self, scope, renderer: QtLineRenderer, info_bar: QtInfoBar) -> None:
        super().__init__()
        self.configuration_scope = scope
        self._info_bar = info_bar
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        renderer.themed(self, lambda: self.setStyleSheet(f"color: {renderer.theme(SecondaryColour)}"))

    def present_status(self, status) -> None:
        text = str(status)
        self.setText(text)
        self.setToolTip(text)
        self._info_bar.sync_visibility()


class QtEditingModeBadge(EditingModeBadge, QLabel, metaclass=PyQtWidgetMeta):
    """The editing mode in reverse video at the info bar's right edge.

    Hidden when vim/modal editing is off (`Standard`), so non-vim mobile composers do not
    spend a full row advertising `STANDARD`."""

    def __init__(self, renderer: QtLineRenderer, info_bar: QtInfoBar) -> None:
        super().__init__()
        self._info_bar = info_bar
        renderer.themed(self, lambda: self.setStyleSheet(
            f"color: {renderer.theme(self.badge_foreground)}; background: {renderer.theme(self.badge_background)};"
            " padding: 0 4px"))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.hide()

    def present_editing_mode(self, mode, focused: bool) -> None:
        shown = mode if focused else Standard()
        if mode.shows_badge:
            self.show_mode_label(shown.label)
            self.show()
        else:
            self.setText("")
            self.hide()
        self._info_bar.sync_visibility()

    def show_mode_label(self, label: str) -> None:
        self.setText(label)


class QtInfoBar(QtSettingVisibility, QWidget, setting="ui.info_bar", metaclass=PyQtWidgetMeta):
    """Under the prompt frame: the composer's directory (a CLI thread's), the status line and
    the editing-mode badge, in Textual's `InfoBar` order. Collapses to 0 height when none of
    its children have anything to show."""

    def __init__(self, scope, renderer: QtLineRenderer, parent: QWidget) -> None:
        # Parented at construction: a parentless widget shown is a top-level window with its
        # own EGL surface, which deadlocks Android's accessibility bridge (SIGABRT "Failed
        # to acquire deadlock protector … eglSurface()").
        super().__init__(parent)
        self.configuration_scope = scope
        self.path = ElidedLine()
        renderer.themed(self.path, lambda: self.path.setStyleSheet(f"color: {renderer.theme(SecondaryColour)}"))
        self.path.hide()
        self.status = QtStatusLine(scope, renderer, self)
        self.badge = QtEditingModeBadge(renderer, self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(UiGap.frame, 0, UiGap.frame, UiGap.tight)
        layout.setSpacing(UiGap.loose)
        layout.addWidget(self.path, 1)
        # Without a path (a message prompt) the free space sits left of the status, so the
        # status and badge keep to the right edge as Textual docks them.
        layout.addStretch(0)
        layout.addWidget(self.status)
        layout.addWidget(self.badge)

    def setting_visible(self, configuration_state) -> bool:
        return super().setting_visible(configuration_state) and self._has_content()

    def _has_content(self) -> bool:
        if not self.path.isHidden() and bool(self.path.text()):
            return True
        if not self.status.isHidden() and bool(self.status.text()):
            return True
        if not self.badge.isHidden() and bool(self.badge.text()):
            return True
        layout = self.layout()
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is not None and widget not in (self.path, self.status, self.badge) and not widget.isHidden():
                return True
        return False

    def sync_visibility(self) -> None:
        self.apply_setting_visibility()

    def show_path(self, path: str) -> None:
        self.path.setText(path)
        self.path.setToolTip(path)
        self.path.setVisible(bool(path))
        self.sync_visibility()
