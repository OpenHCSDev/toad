"""Qt settings screen: the shared form family (`toad.form_family`, formbridge) drawn in Qt.

Which editor edits a field, how text is read back, what a select lists, how fields
nest, how the form splits into pages, searches, marks changes and finishes, and what
discard does are all inherited from the parents Textual's settings screen inherits.
This module adds only Qt widgets, painting and signal wiring.

A Qt editor or field view is a family member that owns its widget (`self.widget`)
rather than being a QWidget: formbridge's families declare members with the `shows=`
class keyword, which shiboken's metaclass refuses on QWidget subclasses.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Optional

import shiboken6
from formbridge.forms.declared_fields import DeclaredField, Multiline
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from formbridge.forms.value_editing import ChoicesEditing, EnumEditing, MultilineEditing, OptionalEditing, ValueEditing
from objectstate import ObjectState
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from python_introspect import AnnotationChoices

from toad.form_family import (
    FieldEditing,
    FieldForm,
    FieldViews,
    GroupFields,
    LineFieldEditing,
    SchemeChoosing,
    SelectFieldEditing,
    StructuredFieldEditing,
    ValueFields,
)
from toad.setting_choices import SchemeName
from toad.settings_editing import SettingsEditing

if TYPE_CHECKING:
    from toad.qt.window import QtToadApp


def _stacked(*widgets: QWidget) -> QWidget:
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    for widget in widgets:
        layout.addWidget(widget)
    return holder


# The editors.

class QtValueEditor(FieldEditing, ABC):
    """A Qt control that shows one field's value and sends the user's edits to the state.

    The value lives in the ObjectState; the control is painted from it. Validation
    feedback shows under the control until the next accepted edit.
    """

    control: QWidget
    widget: QWidget

    def bind_control(self) -> None:
        self.control = self.build_control()
        self.refusal = QLabel()
        self.refusal.setWordWrap(True)
        self.refusal.setStyleSheet("color: palette(link-visited);")
        self.refusal.hide()
        self.widget = _stacked(self.control, self.refusal)
        self.paint()

    @abstractmethod
    def build_control(self) -> QWidget:
        """Build the native control and connect its edits."""

    def display_feedback(self, text: str) -> None:
        self.refusal.setText(text)
        self.refusal.setVisible(bool(text))

    def clear_feedback(self) -> None:
        self.refusal.hide()

    def alive(self) -> bool:
        return shiboken6.isValid(self.control)


class QtBoolEditor(QtValueEditor, shows=(bool,)):
    def build_control(self) -> QCheckBox:
        box = QCheckBox()
        box.toggled.connect(self.send)
        return box

    def paint(self) -> None:
        self.control.blockSignals(True)
        self.control.setChecked(bool(self.field.value))
        self.control.blockSignals(False)


class QtLineEditor(LineFieldEditing, QtValueEditor):
    """One line of text, read as the field's type when the user leaves it or presses enter."""

    def build_control(self) -> QLineEdit:
        line = QLineEdit()
        line.editingFinished.connect(self.finish)
        return line

    def finish(self) -> None:
        self.commit(self.control.text())

    def paint(self) -> None:
        self.control.blockSignals(True)
        self.control.setPlaceholderText(self.placeholder_text())
        self.control.setText(self.current_text())
        self.control.blockSignals(False)


class QtIntEditor(QtLineEditor, shows=(int,)):
    pass


class QtFloatEditor(QtLineEditor, shows=(float,)):
    pass


class QtStrEditor(QtLineEditor, shows=(str,)):
    pass


class QtStructuredEditor(StructuredFieldEditing, QtLineEditor, shows=(tuple, list, dict)):
    pass


class QtMultilineEditor(MultilineEditing, QtValueEditor, shows=(Multiline,)):
    def build_control(self) -> QPlainTextEdit:
        text = QPlainTextEdit()
        text.setFixedHeight(text.fontMetrics().lineSpacing() * 6)
        text.textChanged.connect(lambda: self.send(self.control.toPlainText()))
        return text

    def paint(self) -> None:
        value = str(self.field.value or "")
        if self.control.toPlainText() != value:
            self.control.blockSignals(True)
            self.control.setPlainText(value)
            self.control.blockSignals(False)


class QtSelectEditor(SelectFieldEditing, QtValueEditor):
    """One of a list of values. A value that is not on the list shows as its own text."""

    def build_control(self) -> QComboBox:
        combo = QComboBox()
        combo.activated.connect(lambda index: self.send(self.control.itemData(index)))
        self.install_options(combo)
        return combo

    def install_options(self, combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, choice in self.options():
            combo.addItem(label, choice)
        combo.blockSignals(False)

    def displayed_options(self):
        return ((self.control.itemText(index), self.control.itemData(index))
                for index in range(self.control.count()))

    def paint(self) -> None:
        value = self.field.value
        self.control.blockSignals(True)
        chosen = next((index for index, (_, choice) in enumerate(self.displayed_options())
                       if self.shows_choice(value) and choice == value), -1)
        self.control.setCurrentIndex(chosen)
        self.control.setPlaceholderText(self.value_text(value))
        self.control.blockSignals(False)


class QtChoicesEditor(ChoicesEditing, QtSelectEditor, shows=(AnnotationChoices,)):
    def paint(self) -> None:
        self.install_options(self.control)
        super().paint()


class QtEnumEditor(EnumEditing, QtSelectEditor, shows=(Enum,)):
    pass


class QtSchemeEditor(SchemeChoosing, QtSelectEditor, shows=(SchemeName,)):
    pass


class QtOptionalEditor(OptionalEditing, QtValueEditor, shows=(Optional,)):
    """A field that may hold nothing: a box says whether it holds a value, and the
    editor of that value is shown while it does."""

    def build_control(self) -> QWidget:
        self.holds_value = QCheckBox("Set")
        self.holds_value.toggled.connect(self.change_held)
        self._member = QtValueEditor.declared_for(self.field.member)
        return _stacked(self.holds_value, self._member.widget)

    @property
    def member_editor(self) -> ValueEditing:
        return self._member

    def set_member_shown(self, held: bool) -> None:
        self._member.widget.setVisible(held)

    def paint_held(self, held: bool) -> None:
        self.holds_value.blockSignals(True)
        self.holds_value.setChecked(held)
        self.holds_value.blockSignals(False)

    def paint(self) -> None:
        held = self.field.value is not None
        self.paint_held(held)
        self.set_member_shown(held)
        self._member.paint()


# The field views.

class QtFieldView(FieldViews, ABC):
    """One parameter of a form drawn in Qt; `widget` is what the form lays out."""

    widget: QWidget

    def __init__(self, field: DeclaredField) -> None:
        self.field = field

    @classmethod
    def family(cls):
        return QtFieldView

    def show_field(self, shown: bool) -> None:
        self.widget.setVisible(shown)


class QtValueView(ValueFields, QtFieldView, shows=(ParameterInfo,)):
    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.editor = self.editor_for(QtValueEditor)
        self.title = QLabel(field.label)
        bold = QFont(self.title.font())
        bold.setBold(True)
        self.title.setFont(bold)
        notes = "\n".join(part for part in (field.help, self.accepts_text, self.editor.default_note().strip()) if part)
        self.help = QLabel(notes)
        self.help.setWordWrap(True)
        self.help.setEnabled(False)
        self.help.setVisible(bool(notes))
        self.widget = _stacked(self.title, self.help, self.editor.widget)

    def mark(self, changed: bool) -> None:
        self.title.setText(self.field.label + self.changed_mark(changed))


class QtGroupView(GroupFields, QtFieldView, shows=(DirectDataclassInfo,)):
    field_family = QtFieldView

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.build_parts()
        box = QGroupBox(field.label)
        layout = QVBoxLayout(box)
        if field.help:
            note = QLabel(field.help)
            note.setWordWrap(True)
            note.setEnabled(False)
            layout.addWidget(note)
        for part in self.parts:
            layout.addWidget(part.widget)
        self.widget = box


class QtFormView(FieldForm):
    """Every field of one page, scrolled; repaints the fields the state says changed."""

    field_family = QtFieldView

    def __init__(self, state: ObjectState, parts: list[QtFieldView]) -> None:
        self.state = state
        self.parts = parts
        self.build_index()
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        for part in parts:
            layout.addWidget(part.widget)
        layout.addStretch(1)
        self.widget = QScrollArea()
        self.widget.setWidgetResizable(True)
        self.widget.setWidget(inner)

    def repaint_editor(self, editor: QtValueEditor) -> None:
        if editor.alive():
            editor.paint()


# The screen.

class QtSettingsScreen(SettingsEditing, QDialog):
    """Modal settings editor: a search above one tab per declared page. Discard rolls
    back unsaved edits; closing sends the typed edits and the app saves them."""

    closed = Signal()

    def __init__(self, app: QtToadApp, parent: QWidget | None = None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.setWindowFlags(Qt.WindowType.Dialog)
        self.setWindowTitle("Settings")
        self.build_pages()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search settings")
        self.search.textChanged.connect(self.filter_pages)
        layout.addWidget(self.search)
        self.tabs = QTabWidget(self)
        for page, form in self.pages.items():
            self.tabs.addTab(form.widget, page.title or "Settings")
        layout.addWidget(self.tabs, stretch=1)
        buttons = QDialogButtonBox(self)
        buttons.addButton("Discard changes", QDialogButtonBox.ButtonRole.ResetRole).clicked.connect(self.discard)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.close)
        layout.addWidget(buttons)

        for form in self.pages.values():
            form.follow_state()
        self.start_editing()

    @property
    def edited_settings(self):
        return self.app.saved_settings

    @classmethod
    def form_type(cls):
        return QtFormView

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.finish()
        self.stop_editing()
        for form in self.pages.values():
            form.leave_state()
        asyncio.ensure_future(self.app.settings_closed())
        self.closed.emit()
        super().closeEvent(event)
