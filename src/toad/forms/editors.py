"""One control per kind of value, chosen by what the field declares."""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterable
from enum import Enum
from typing import ClassVar, Optional

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import (
    DeclaredField,
    Multiline,
)
from formbridge.forms.value_editing import (
    ChoicesEditing,
    ControlConstruction,
    EnumEditing,
    LineEditing,
    MultilineEditing,
    OptionalEditing,
    SelectEditing,
)
from python_introspect import (
    AnnotationChoices,
    resolve_annotated,
)
from textual import containers, events
from textual.app import ComposeResult
from textual.css.scalar import Scalar
from textual.geometry import Spacing
from textual.message import Message
from textual.reactive import var
from textual.validation import Function
from textual.view import WidgetView
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Select, TextArea
from textual.widgets._input import InputType
from ui_theme.scheme import MutedColour

from toad.forms.presentation import (
    FormCheckbox,
    FormInput,
    FormSelectCurrent,
    FramedControl,
)
from toad.tone_paint import UntintedTonePaint


class ValueEditor(ControlConstruction, Widget):
    """A control that shows one field's value and sends the user's edits to the state.

    The value lives in the ObjectState: the control is painted from it. Only
    transient validation feedback lives here. The editor binds the field before the native
    control is initialized: `class BoolEditor(ValueEditor, Checkbox)`.
    """

    feedback: var[str] = var("", init=False)

    class Feedback(Message):
        """Transient validation text for the field's own view, never a crash log."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.listen(events.Mount, self.control_mounted)

    @property
    def previewing(self) -> bool:
        return self.field.state.parameters[self.field.path.value] is None and self.field.value is not None

    def paint_value(self) -> None:
        self.paint()
        self.styles.color = self.app.colours.colour(MutedColour) if self.previewing else None
        self.styles.text_style = "dim" if self.previewing else None

    def control_mounted(self, event: events.Mount) -> None:
        self.call_after_refresh(self.paint_value)

    @abstractmethod
    def bind_control(self) -> None:
        """Connect the native control's edits after it has been initialized."""

    @abstractmethod
    def paint(self) -> None:
        """Paint the control from the state."""

    def display_feedback(self, text: str) -> None:
        self.feedback = text
        self.paint()

    def clear_feedback(self) -> None:
        self.feedback = ""

    def watch_feedback(self, text: str) -> None:
        self.post_message(self.Feedback(text))


class BoolEditor(ValueEditor, FormCheckbox, shows=(bool,)):
    def control_arguments(self) -> dict[str, object]:
        return {"value": bool(self.field.value)}

    def bind_control(self) -> None:
        self.listen(Checkbox.Changed, self.changed)

    def changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.send(message.value)

    def paint(self) -> None:
        with self.prevent(Checkbox.Changed):
            self.value = bool(self.field.value)


class LineEditor(LineEditing, ValueEditor, FormInput):
    """One line of text, read as the field's type when the user leaves it or presses enter."""

    accepts: ClassVar[InputType]

    def current_text(self) -> str:
        return "" if self.previewing else self.value_text(self.field.value)

    def control_arguments(self) -> dict[str, object]:
        return {
            "value": self.current_text(),
            "placeholder": self.value_text(self.field.value) if self.previewing else self.field.placeholder,
            "type": self.accepts,
            "validators": [Function(self.acceptable)],
        }

    def bind_control(self) -> None:
        self.listen(Input.Blurred, self.finished)
        self.listen(Input.Submitted, self.finished)

    def read(self, text: str) -> object:
        return resolve_annotated(self.field.annotation)(text)  # type: ignore[operator]

    def finished(self, message: Input.Blurred | Input.Submitted) -> None:
        message.stop()
        self.finish()

    def finish(self) -> None:
        if self.value == self.current_text():
            return
        try:
            value = self.read(self.value)
        except ValueError as error:
            self.refuse(error)
        else:
            self.send(value)

    def paint(self) -> None:
        self.placeholder = self.value_text(self.field.value) if self.previewing else self.field.placeholder
        self.value = self.current_text()


class IntEditor(LineEditor, shows=(int,)):
    accepts = "integer"


class FloatEditor(LineEditor, shows=(float,)):
    accepts = "number"


class StrEditor(LineEditor, shows=(str,)):
    accepts = "text"


class StructuredEditor(LineEditor, shows=(tuple, list, dict)):
    """A JSON value checked against the complete declared collection type."""
    accepts = "text"

    def value_text(self, value: object) -> str:
        return json.dumps(FieldCodec.encode(value), ensure_ascii=False)

    def read(self, text: str) -> object:
        return FieldCodec.decode(self.field.annotation, FieldCodec.parse(text.encode()))


class MultilineEditor(MultilineEditing, ValueEditor, UntintedTonePaint, FramedControl, TextArea, shows=(Multiline,)):
    height = Scalar.from_number(10)
    padding = Spacing(0, 1, 0, 1)

    def control_arguments(self) -> dict[str, object]:
        return {"text": str(self.field.value or "")}

    def bind_control(self) -> None:
        self.listen(TextArea.Changed, self.changed)

    def changed(self, message: TextArea.Changed) -> None:
        message.stop()
        self.send(self.text)

    def paint(self) -> None:
        value = str(self.field.value or "")
        if self.text != value:
            with self.prevent(TextArea.Changed):
                self.load_text(value)


class SelectEditor(SelectEditing, ValueEditor, WidgetView, Select[object]):
    """One of a list of values. A value that is not on the list shows as its own text."""

    CURRENT = FormSelectCurrent

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        if self.is_mounted:
            self.query_one(FormSelectCurrent).refresh_paint()

    def control_arguments(self) -> dict[str, object]:
        options = tuple(self.options())
        value = self.field.value
        listed = not self.previewing and any(value == choice for _, choice in options)
        return {
            "options": options,
            "value": value if listed else Select.NULL,
            "allow_blank": True,
            "prompt": next((label for label, choice in options if choice == value),
                           self.field.placeholder if value is None else str(value)),
        }

    def bind_control(self) -> None:
        self.listen(Select.Changed, self.changed)

    def displayed_options(self) -> Iterable[tuple[str, object]]:
        return self._options

    def changed(self, message: Select.Changed) -> None:
        message.stop()
        if message.value is not Select.NULL:
            self.send(message.value)

    def paint(self) -> None:
        value = self.field.value
        with self.prevent(Select.Changed):
            self.prompt = self.value_text(value)
            self.value = value if not self.previewing and self.lists(value) else Select.NULL


class ChoicesEditor(ChoicesEditing, SelectEditor, shows=(AnnotationChoices,)):
    def paint(self) -> None:
        with self.prevent(Select.Changed):
            self.set_options(self.options())
            super().paint()


class EnumEditor(EnumEditing, SelectEditor, shows=(Enum,)):
    pass


class OptionalEditor(OptionalEditing, ValueEditor, WidgetView, containers.VerticalGroup, shows=(Optional,)):
    """A field that may hold nothing: a box says whether it holds a value, and the
    editor of that value is shown while it does."""

    def bind_control(self) -> None:
        self.holds_value = FormCheckbox("Set", value=self.field.value is not None)
        self._member = ValueEditor.declared_for(self.field.member)
        self._member.listen(ValueEditor.Feedback, self.member_feedback)
        self._member.display = self.field.value is not None
        self.holds_value.listen(Checkbox.Changed, self.held_changed)

    @property
    def member_editor(self) -> ValueEditor:
        return self._member

    def compose(self) -> ComposeResult:
        yield self.holds_value
        yield self._member

    def member_feedback(self, message: ValueEditor.Feedback) -> None:
        message.stop()
        self.feedback = message.text

    def set_member_shown(self, held: bool) -> None:
        self._member.display = held

    def paint_held(self, held: bool) -> None:
        with self.prevent(Checkbox.Changed):
            self.holds_value.value = held

    def held_changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.change_held(message.value)

    def paint(self) -> None:
        held = self.field.value is not None
        self.paint_held(held)
        self._member.display = held
        self._member.paint()
