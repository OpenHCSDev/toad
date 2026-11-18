"""Qt's form family: the shared form layer (`toad.form_family`, formbridge) drawn in Qt.

Any Qt form host uses these: the settings screen, a thread's view-settings pane, any
ObjectState form. Which editor edits a field, how its text is read back, what a select
lists, validation and write-back, how fields nest, and how a form follows its state and
marks changes are inherited from the parents Textual's `toad.forms` inherits. This module
adds only Qt widgets, painting and signal wiring.

A Qt editor or field view is a family member that owns its widget (`self.widget`) rather
than being a QWidget: formbridge's families declare members with the `shows=` class
keyword, which shiboken's metaclass refuses on QWidget subclasses. A sub-family (an
object form's views) subclasses `QtFieldView` and names itself as `family()`, as Textual's
`ObjectFieldView` does under `FieldView`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from functools import cached_property
from typing import Optional

import shiboken6
from formbridge.forms.declared_fields import DeclaredField, Multiline
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from formbridge.forms.value_editing import ChoicesEditing, EnumEditing, MultilineEditing, OptionalEditing, ValueEditing
from objectstate import ObjectState
from PySide6.QtGui import QFont
from pyqt_reactive.theming.themed_checkbox import ThemedCheckBox
from PySide6.QtWidgets import (
    QCheckBox,
    QPushButton,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
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
    ObjectValueFields,
    SchemeChoosing,
    SelectFieldEditing,
    StructuredFieldEditing,
    ValueFields,
)
from toad.object_configuration import ObjectSettingField
from toad.qt.lines import QtLineRenderer
from toad.setting_choices import SchemeName


GROUP_HEADING = "form-group-heading"


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
        box = ThemedCheckBox()
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
        # Fit the form's width, not the longest choice: a narrow sidebar page must not scroll sideways.
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
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
        self.holds_value = ThemedCheckBox("Set")
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
        self.title.setWordWrap(True)
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
        # A wrapped heading in a plain frame, as the TUI draws a group: a QGroupBox title
        # cannot wrap, and its width would hold a narrow sidebar page open.
        box = QFrame()
        box.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(box)
        heading = QLabel(field.label)
        heading.setObjectName(GROUP_HEADING)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if field.help:
            note = QLabel(field.help)
            note.setWordWrap(True)
            note.setEnabled(False)
            layout.addWidget(note)
        for part in self.parts:
            layout.addWidget(part.widget)
        self.widget = box


class QtFormView(FieldForm):
    """Every field of one page; repaints the fields the state says changed. `body` holds
    the fields; `widget` is that body scrolled, for a host that does not scroll it itself."""

    field_family = QtFieldView

    def __init__(self, state: ObjectState, parts: list[QtFieldView]) -> None:
        self.state = state
        self.parts = parts
        self.build_index()
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        for part in parts:
            layout.addWidget(part.widget)
        layout.addStretch(1)

    def theme(self, renderer: QtLineRenderer) -> None:
        """Colour what the shared family declares a colour for, from the app's scheme."""
        self.body.setStyleSheet(f"#{GROUP_HEADING} {{ color: {renderer.theme(GroupFields.heading_colour)} }}")

    @cached_property
    def widget(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        return scroll

    def repaint_editor(self, editor: QtValueEditor) -> None:
        if editor.alive():
            editor.paint()




# A viewed object's settings: the sub-family Textual's `ObjectFieldView` is.

class QtObjectFieldView(QtFieldView):
    """A field of a viewed object's configuration; an edit goes through the view's
    configuration (`ObjectSettingField.edit`), not the global settings."""

    field_type = ObjectSettingField

    @classmethod
    def family(cls):
        return QtObjectFieldView


class QtObjectValueView(ObjectValueFields, QtValueView, QtObjectFieldView, shows=(ParameterInfo,)):
    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.source = QLabel()
        self.source.setWordWrap(True)
        self.source.setEnabled(False)
        reset = QPushButton(self.reset_label)
        reset.clicked.connect(self.reset_field)
        self.widget.layout().addWidget(self.source)
        self.widget.layout().addWidget(reset)
        self.mark(False)

    def mark(self, changed: bool) -> None:
        overridden = self.overridden()
        super().mark(overridden)
        if self.editor.alive():
            self.editor.paint()
        self.source.setText(self.source_text())
        self.source.setToolTip("" if overridden else self.source_detail())


class QtObjectGroupView(QtGroupView, QtObjectFieldView, shows=(DirectDataclassInfo,)):
    field_family = QtObjectFieldView


class QtObjectFormView(QtFormView):
    field_family = QtObjectFieldView
