"""Qt searchable, recent-first model picker over the shared `ModelSelectionCore`.

Mirrors Textual's `ModelSelection` (`widgets/model_selection.py`) and `CatalogField` /
`CatalogFieldSelection` (`widgets/comms_command_dialog.py`): fuzzy scoring, recent-first /
current-first ordering, highlight retention across refilters, and `ModelConfigOption`
binding all come from `toad.client.model_selection`. Importing this module registers
`QtCatalogField` on `QtValueEditor` for `ModelConfigOption`, so every Qt command form
(`start`, `configure`, `fork`) automatically uses the searchable model picker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import shiboken6
from agent_comms.config_options import ModelConfigOption
from formbridge.forms.value_editing import ControlConstruction
from pyqt_reactive.forms.declared_editors import QtValueEditor
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from toad.acp.agent_configuration import ModelConfigurationSetting
from toad.client.model_selection import (
    CatalogChoiceSelection,
    CatalogModelField,
    ModelSelectionCore,
    RankedModel,
    ResetsHighlight,
    SessionChoiceSelection,
)
from toad.qt.presented_window import PresentedWindow
from toad.widget_contracts import DismissibleContract, SubmitsContract


class QtModelSelection(
    ModelSelectionCore,
    QWidget,
    DismissibleContract,
    SubmitsContract,
    metaclass=PyQtWidgetMeta,
):
    """Searchable, recently-used-first model picker widget on Qt."""

    MODEL_ID_ROLE = Qt.ItemDataRole.UserRole

    def __init__(
        self,
        *,
        on_selected: Callable[[str], None],
        on_dismiss: Callable[[], None],
        on_connect: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self._on_selected = on_selected
        self._on_dismiss = on_dismiss
        self._on_connect = on_connect
        super().__init__(parent)
        self.init_model_selection()
        self._recents_task: asyncio.Task[None] | None = None
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(f"Search {self.choice_name} or providers…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self.submit)
        self.search_input.installEventFilter(self)

        self.count_label = QLabel("", self)
        self.option_list = QListWidget(self)
        self.option_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.option_list.currentRowChanged.connect(self._on_row_highlighted)
        self.option_list.itemClicked.connect(self._on_item_activated)
        self.option_list.itemActivated.connect(self._on_item_activated)

        self.connect_button = QPushButton("Connect a provider…", self)
        self.connect_button.clicked.connect(self.connect_provider)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addWidget(self.count_label)
        layout.addWidget(self.option_list, 1)
        layout.addWidget(self.connect_button)

    @property
    def selection_active(self) -> bool:
        return shiboken6.isValid(self) and self.isVisible()

    def open_selection(self) -> None:
        """Reset search state, rank choices immediately, and load recents asynchronously."""
        self._open_generation += 1
        self.refilter = ResetsHighlight()
        self.recent_ids = []
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.filter_models(self.refilter)
        self.search_input.setFocus()
        self._start_recents(self._open_generation, self.history_scope)

    def _start_recents(self, generation: int, scope: str) -> None:
        if self._recents_task is not None and not self._recents_task.done():
            self._recents_task.cancel()
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._recents_task = asyncio.ensure_future(self._load_recents(generation, scope))

    async def _load_recents(self, generation: int, scope: str) -> None:
        recent = await self.recent_choices(scope)
        self.apply_recents(generation, scope, recent)

    def search_query(self) -> str:
        return self.search_input.text()

    def highlighted_model_id(self) -> str | None:
        current_item = self.option_list.currentItem()
        return current_item.data(self.MODEL_ID_ROLE) if current_item is not None else None

    def present_filtered_models(
        self,
        ranked: list[RankedModel],
        highlighted_index: int | None,
        summary: str,
    ) -> None:
        self.option_list.blockSignals(True)
        self.option_list.clear()
        for entry in ranked:
            item = QListWidgetItem(entry.plain_label)
            item.setData(self.MODEL_ID_ROLE, entry.choice.value)
            if entry.choice.description:
                item.setToolTip(entry.choice.description)
            self.option_list.addItem(item)
        self.option_list.setCurrentRow(highlighted_index if highlighted_index is not None else -1)
        self.option_list.blockSignals(False)
        self.count_label.setText(summary)

    def _on_search_changed(self, _text: str) -> None:
        self.search_changed()

    def _on_row_highlighted(self, _row: int) -> None:
        self.note_highlight_moved()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        model_id = item.data(self.MODEL_ID_ROLE)
        if model_id is not None:
            self.select_model(model_id)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            count = self.option_list.count()
            if key == Qt.Key.Key_Down and count:
                row = min(count - 1, self.option_list.currentRow() + 1)
                self.option_list.setCurrentRow(row)
                return True
            if key == Qt.Key.Key_Up and count:
                row = max(0, self.option_list.currentRow() - 1)
                self.option_list.setCurrentRow(row)
                return True
            if key == Qt.Key.Key_Escape:
                self.dismiss_control()
                return True
        return super().eventFilter(watched, event)


    def select_model(self, model_id: str) -> None:
        self._on_selected(model_id)

    def dismiss_control(self) -> None:
        self._on_dismiss()

    def connect_provider(self) -> None:
        self._on_connect()


class QtCatalogFieldSelection(CatalogChoiceSelection, QtModelSelection):
    """Qt model selection bound to a `QtCatalogField` editor."""

    def __init__(
        self,
        editor: CatalogModelField,
        *,
        on_selected: Callable[[str], None],
        on_dismiss: Callable[[], None],
        on_connect: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self.editor = editor
        super().__init__(
            on_selected=on_selected,
            on_dismiss=on_dismiss,
            on_connect=on_connect,
            parent=parent,
        )


class QtSessionModelSelection(SessionChoiceSelection, QtModelSelection):
    """Qt model selection bound to an ACP session's live `ModelConfigurationSetting`."""

    def __init__(
        self,
        setting_provider: Callable[[], ModelConfigurationSetting],
        history_scope: str,
        *,
        on_selected: Callable[[str], None],
        on_dismiss: Callable[[], None],
        on_connect: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self._setting_provider = setting_provider
        self.history_scope = history_scope
        super().__init__(
            on_selected=on_selected,
            on_dismiss=on_dismiss,
            on_connect=on_connect,
            parent=parent,
        )

    def model_setting(self) -> ModelConfigurationSetting:
        return self._setting_provider()


class QtModelChoiceDialog(PresentedWindow, QDialog, DismissibleContract, metaclass=PyQtWidgetMeta):
    """Modal `PresentedWindow` hosting a `QtModelSelection` without a nested event loop."""

    dismiss_control = QDialog.reject

    def __init__(
        self,
        selection_factory: Callable[[QtModelChoiceDialog], QtModelSelection],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose model")
        self.chosen: str | None = None
        self.selection = selection_factory(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.selection)
        self.resize(520, 480)

    @classmethod
    def for_catalog_field(cls, editor: QtCatalogField, parent: QWidget | None = None) -> QtModelChoiceDialog:
        return cls(
            lambda dialog: QtCatalogFieldSelection(
                editor,
                on_selected=dialog._accept_model,
                on_dismiss=dialog.reject,
                on_connect=dialog._connect_provider,
                parent=dialog,
            ),
            parent,
        )

    @classmethod
    def for_session(
        cls,
        setting_provider: Callable[[], ModelConfigurationSetting],
        history_scope: str,
        parent: QWidget | None = None,
    ) -> QtModelChoiceDialog:
        return cls(
            lambda dialog: QtSessionModelSelection(
                setting_provider,
                history_scope,
                on_selected=dialog._accept_model,
                on_dismiss=dialog.reject,
                on_connect=dialog._connect_provider,
                parent=dialog,
            ),
            parent,
        )

    def _accept_model(self, model_id: str) -> None:
        self.chosen = model_id
        self.accept()

    def _connect_provider(self) -> None:
        self.selection.count_label.setText("Run provider login from a terminal to connect a provider")

    def open_picker(self) -> None:
        self.open()
        self.selection.open_selection()


class QtCatalogFieldBase(CatalogModelField, ControlConstruction, QtValueEditor):
    """Combined non-Qt editing base so `QtCatalogField` stays within Shiboken's 3-base cap."""


class QtCatalogField(
    QtCatalogFieldBase,
    QPushButton,
    metaclass=PyQtWidgetMeta,
    shows=(ModelConfigOption,),
):
    """Qt sibling of Textual's `CatalogField`: opens `QtModelChoiceDialog` on click."""

    def bind_control(self) -> None:
        self._dialog: QtModelChoiceDialog | None = None
        self.clicked.connect(self.choose)
        self.paint()

    def paint(self) -> None:
        self.setText(self.catalog_label())

    def choose(self) -> None:
        dialog = QtModelChoiceDialog.for_catalog_field(self, self.window())
        self._dialog = dialog
        dialog.finished.connect(self._dialog_finished)
        dialog.open_picker()

    def _dialog_finished(self, result: int) -> None:
        dialog, self._dialog = self._dialog, None
        if dialog is None:
            return
        chosen = dialog.chosen
        dialog.deleteLater()
        if result == int(QDialog.DialogCode.Accepted) and chosen is not None and shiboken6.isValid(self):
            self.apply_catalog_choice(chosen)
            self.paint()
