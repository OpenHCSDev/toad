"""Qt's unified interactive dialog panel: renders `DialogSpec` inline in any conversation.

Single-choice questions, multi-select checklists, confirmations, text/number inputs, and
ACP `elicitation/create` forms all render through this one widget inheriting the shared
`InteractiveDialogOwner` state machine (`toad.client.interactive_dialog`). Every child
widget is parented to this frame so Android never spawns stray top-level EGL windows.
"""

from __future__ import annotations

from functools import partial

from metaclass_registry.mro_dispatch import MroDispatch, handles
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from pyqt_reactive.theming.themed_checkbox import ThemedCheckBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from toad.client.input_attention import InputAttention
from toad.client.interactive_dialog import (
    ConfirmDialogField,
    DialogField,
    DialogSpec,
    InteractiveDialogOwner,
    MultiSelectDialogField,
    NumberDialogField,
    SingleSelectDialogField,
    TextDialogField,
)
from toad.qt.metrics import UiGap, delete_layout_widgets
from toad.widget_contracts import DismissibleContract, SubmitsContract


class QtInteractiveDialog(
    InteractiveDialogOwner,
    MroDispatch,
    QFrame,
    DismissibleContract,
    SubmitsContract,
    metaclass=PyQtWidgetMeta,
):
    """Inline interactive dialog docked under a Qt conversation's composer."""

    def __init__(self, app, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.init_dialog_owner()
        self.app = app
        self.attention: InputAttention = app.input_attention
        self.destroyed.connect(partial(self.attention.release, self))

        self._title = QLabel(self)
        title_font = QFont(self._title.font())
        title_font.setBold(True)
        self._title.setFont(title_font)
        self._title.setWordWrap(True)

        self._message = QLabel(self)
        self._message.setWordWrap(True)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setMaximumHeight(280)
        self._body = QWidget(self._scroll)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(UiGap.normal)
        self._scroll.setWidget(self._body)

        self._actions_row = QHBoxLayout()
        self._actions_row.setContentsMargins(0, UiGap.tight, 0, 0)
        self._actions_row.setSpacing(UiGap.normal)
        self._submit_button = QPushButton("Submit", self)
        self._submit_button.clicked.connect(self.commit_dialog)
        self._decline_button = QPushButton("Decline", self)
        self._decline_button.clicked.connect(self.decline_dialog)
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.clicked.connect(self.cancel_dialog)
        self._actions_row.addWidget(self._submit_button)
        self._actions_row.addWidget(self._decline_button)
        self._actions_row.addWidget(self._cancel_button)
        self._actions_row.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(UiGap.wide, UiGap.frame, UiGap.wide, UiGap.frame)
        root.setSpacing(UiGap.tight)
        root.addWidget(self._title)
        root.addWidget(self._message)
        root.addWidget(self._scroll)
        root.addLayout(self._actions_row)

        self._error_labels: dict[str, QLabel] = {}
        self._button_groups: list[QButtonGroup] = []
        self._first_focus: QWidget | None = None
        self.hide()

    def submit(self) -> None:
        self.commit_dialog()

    def dismiss_control(self) -> None:
        self.cancel_dialog()

    def present_dialog(self, spec: DialogSpec) -> None:
        self._clear_body()
        self._title.setText(spec.title)
        self._title.setVisible(bool(spec.title))
        self._message.setText(spec.message)
        self._message.setVisible(bool(spec.message))
        self._submit_button.setText(spec.submit_label)
        self._decline_button.setText(spec.decline_label)
        self._cancel_button.setText(spec.cancel_label)
        quick = spec.is_quick_choice
        self._submit_button.setVisible(not quick)
        self._decline_button.setVisible(not quick)

        for field in spec.fields:
            section = self._build_field_section(field, quick=quick)
            self._body_layout.addWidget(section)
        self._body_layout.addStretch(1)

        if self.parentWidget() is not None:
            self.show()
        self.attention.require(self)
        if self._first_focus is not None:
            self._first_focus.setFocus()

    def clear_dialog(self) -> None:
        self._clear_body()
        self.hide()
        self.attention.release(self)

    def show_dialog_errors(self, errors: dict[str, str]) -> None:
        for name, label in self._error_labels.items():
            text = errors.get(name, "")
            label.setText(text)
            label.setVisible(bool(text))

    def _clear_body(self) -> None:
        delete_layout_widgets(self._body_layout)
        self._error_labels.clear()
        self._button_groups.clear()
        self._first_focus = None

    def _remember_focus(self, widget: QWidget) -> None:
        if self._first_focus is None:
            self._first_focus = widget

    def _build_field_section(self, field: DialogField, *, quick: bool) -> QWidget:
        section = QWidget(self._body)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UiGap.tight)
        if not quick:
            heading = QLabel(field.title, section)
            heading_font = QFont(heading.font())
            heading_font.setBold(True)
            heading.setFont(heading_font)
            heading.setWordWrap(True)
            layout.addWidget(heading)
        if field.description:
            desc = QLabel(field.description, section)
            desc.setWordWrap(True)
            desc.setEnabled(False)
            layout.addWidget(desc)
        control = next(self.handlers_for(field))(field, section, quick)
        layout.addWidget(control)
        error = QLabel(section)
        error.setWordWrap(True)
        error.setStyleSheet("color: palette(link-visited);")
        error.hide()
        layout.addWidget(error)
        self._error_labels[field.name] = error
        return section

    @handles(SingleSelectDialogField)
    def build_single_select(
        self, field: SingleSelectDialogField, parent: QWidget, quick: bool,
    ) -> QWidget:
        holder = QWidget(parent)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UiGap.tight)
        if quick:
            for option in field.options:
                label = f"{option.label} — {option.description}" if option.description else option.label
                button = QPushButton(label, holder)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, n=field.name, v=option.value: self.pick_quick_option(n, v)
                )
                layout.addWidget(button)
                self._remember_focus(button)
            return holder

        group = QButtonGroup(holder)
        group.setExclusive(True)
        self._button_groups.append(group)
        initial = self.dialog_values.get(field.name)
        other_edit: QLineEdit | None = None
        for option in field.options:
            label = f"{option.label} — {option.description}" if option.description else option.label
            radio = QRadioButton(label, holder)
            radio.setChecked(initial == option.value)
            radio.toggled.connect(
                lambda checked, n=field.name, v=option.value: checked and self.set_dialog_value(n, v)
            )
            group.addButton(radio)
            layout.addWidget(radio)
            self._remember_focus(radio)
        if field.allow_other:
            other_radio = QRadioButton("Other:", holder)
            other_edit = QLineEdit(holder)
            other_edit.setPlaceholderText("Type custom answer...")
            other_edit.setEnabled(False)
            other_radio.toggled.connect(
                lambda checked, edit=other_edit, n=field.name: (
                    edit.setEnabled(checked),
                    self.set_dialog_value(n, edit.text()) if checked else None,
                )
            )
            other_edit.textChanged.connect(
                lambda text, radio=other_radio, n=field.name: (
                    self.set_dialog_value(n, text) if radio.isChecked() else None
                )
            )
            group.addButton(other_radio)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(other_radio)
            row.addWidget(other_edit, 1)
            layout.addLayout(row)
        return holder

    @handles(MultiSelectDialogField)
    def build_multi_select(
        self, field: MultiSelectDialogField, parent: QWidget, quick: bool,
    ) -> QWidget:
        holder = QWidget(parent)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(UiGap.tight)
        selected = set(field.coerce(self.dialog_values.get(field.name)))
        other_state = {"previous": ""}
        for option in field.options:
            label = f"{option.label} — {option.description}" if option.description else option.label
            box = ThemedCheckBox(label, holder)
            box.setChecked(option.value in selected)
            box.toggled.connect(
                lambda checked, n=field.name, v=option.value: self.toggle_dialog_option(n, v, checked)
            )
            layout.addWidget(box)
            self._remember_focus(box)
        if field.allow_other:
            other_edit = QLineEdit(holder)
            other_edit.setPlaceholderText("Other (optional)...")

            def _other_changed(text: str, n: str = field.name) -> None:
                prev = other_state["previous"]
                if prev:
                    self.toggle_dialog_option(n, prev, False)
                cleaned = text.strip()
                other_state["previous"] = cleaned
                if cleaned:
                    self.toggle_dialog_option(n, cleaned, True)

            other_edit.textChanged.connect(_other_changed)
            layout.addWidget(other_edit)
            self._remember_focus(other_edit)
        return holder

    @handles(ConfirmDialogField)
    def build_confirm(
        self, field: ConfirmDialogField, parent: QWidget, quick: bool,
    ) -> QWidget:
        box = ThemedCheckBox(field.title, parent)
        box.setChecked(bool(self.dialog_values.get(field.name)))
        box.toggled.connect(lambda checked, n=field.name: self.set_dialog_value(n, checked))
        self._remember_focus(box)
        return box

    @handles(TextDialogField)
    def build_text(
        self, field: TextDialogField, parent: QWidget, quick: bool,
    ) -> QWidget:
        if field.multiline:
            edit = QPlainTextEdit(parent)
            edit.setPlaceholderText(field.placeholder)
            edit.setPlainText(str(self.dialog_values.get(field.name) or ""))
            edit.setFixedHeight(edit.fontMetrics().lineSpacing() * 4)
            edit.textChanged.connect(lambda e=edit, n=field.name: self.set_dialog_value(n, e.toPlainText()))
            self._remember_focus(edit)
            return edit
        line = QLineEdit(parent)
        line.setPlaceholderText(field.placeholder)
        line.setText(str(self.dialog_values.get(field.name) or ""))
        line.textChanged.connect(lambda text, n=field.name: self.set_dialog_value(n, text))
        line.returnPressed.connect(self.commit_dialog)
        self._remember_focus(line)
        return line

    @handles(NumberDialogField)
    def build_number(
        self, field: NumberDialogField, parent: QWidget, quick: bool,
    ) -> QWidget:
        line = QLineEdit(parent)
        line.setPlaceholderText("Whole number" if field.integer else "Number")
        line.setText(str(self.dialog_values.get(field.name) or ""))
        line.textChanged.connect(lambda text, n=field.name: self.set_dialog_value(n, text))
        line.returnPressed.connect(self.commit_dialog)
        self._remember_focus(line)
        return line
