"""One control per kind of value, chosen by what the field declares."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from formbridge.forms.ui_utils import format_enum_display
from python_introspect import (
    AnnotationChoices,
    declared_annotation_choices,
    resolve_annotated,
)
from python_introspect.validation import validate_annotation_value
from textual import containers
from textual.app import ComposeResult
from textual.validation import Function
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Select, TextArea
from textual.widgets._input import InputType

from toad.forms.declared_views import DeclaredField, DeclaredViews, declarations
from toad.forms.kinds import Multiline

if TYPE_CHECKING:
    EditorWidget = Widget
else:
    EditorWidget = object


class ValueEditor(DeclaredViews, EditorWidget):
    """A control that shows one field's value and sends the user's edits to the state.

    The value lives in the ObjectState: the control is painted from it and
    keeps nothing else. Each member is a Textual control first and an editor
    second: `class BoolEditor(Checkbox, ValueEditor)`.
    """

    states_default: ClassVar[bool] = True
    """Whether the field's help should end with its default value."""

    field: DeclaredField

    @classmethod
    def declared_for(cls, field: DeclaredField) -> ValueEditor:
        return cls.showing(declarations(field.annotation))(field)

    def paint(self) -> None:
        """Paint the control from the state."""
        raise NotImplementedError

    def finish(self) -> None:
        """Send an edit the user has not finished yet. Most controls have none."""

    def value_text(self, value: object) -> str:
        """How a value of this field reads."""
        return str(value)

    def send(self, value: object) -> None:
        try:
            self.field.edit(value)
        except (TypeError, ValueError) as error:
            self.refuse(error)

    def refuse(self, error: Exception) -> None:
        self.notify(str(error), title=self.field.label, severity="error")
        self.paint()


class BoolEditor(Checkbox, ValueEditor):
    shows = (bool,)

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__(value=bool(field.value))
        self.listen(Checkbox.Changed, self.changed)

    def changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.send(message.value)

    def paint(self) -> None:
        with self.prevent(Checkbox.Changed):
            self.value = bool(self.field.value)


class LineEditor(Input, ValueEditor):
    """One line of text, read as the field's type when the user leaves it or presses enter."""

    accepts: ClassVar[InputType]

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__(
            self.value_text(field.value), type=self.accepts, validators=[Function(self.acceptable)]
        )
        self.listen(Input.Blurred, self.finished)
        self.listen(Input.Submitted, self.finished)

    def read(self, text: str) -> object:
        return resolve_annotated(self.field.annotation)(text)  # type: ignore[operator]

    def value_text(self, value: object) -> str:
        return "" if value is None else str(value)

    def acceptable(self, text: str) -> bool:
        try:
            validate_annotation_value(
                self.field.annotation, self.read(text), path=self.field.label
            )
        except (TypeError, ValueError):
            return False
        return True

    def finished(self, message: Input.Blurred | Input.Submitted) -> None:
        message.stop()
        self.finish()

    def finish(self) -> None:
        if self.value == self.value_text(self.field.value):
            return
        try:
            value = self.read(self.value)
        except ValueError as error:
            self.refuse(error)
        else:
            self.send(value)

    def paint(self) -> None:
        self.value = self.value_text(self.field.value)


class IntEditor(LineEditor):
    shows = (int,)
    accepts = "integer"


class FloatEditor(LineEditor):
    shows = (float,)
    accepts = "number"


class StrEditor(LineEditor):
    shows = (str,)
    accepts = "text"


class MultilineEditor(TextArea, ValueEditor):
    shows = (Multiline,)

    DEFAULT_CSS = """
    MultilineEditor {
        height: 10;
    }
    """

    states_default = False

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__(str(field.value or ""))
        self.listen(TextArea.Changed, self.changed)

    def changed(self, message: TextArea.Changed) -> None:
        message.stop()
        self.send(self.text)

    def paint(self) -> None:
        value = str(self.field.value or "")
        if self.text != value:
            with self.prevent(TextArea.Changed):
                self.load_text(value)


class SelectEditor(Select[object], ValueEditor):
    """One of a list of values. A value that is not on the list shows as its own text."""

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        self.offered = tuple(self.options())
        value = field.value
        listed = self.lists(value)
        super().__init__(
            self.offered,
            value=value if listed else Select.NULL,
            allow_blank=not listed,
            prompt="" if value is None else self.value_text(value),
        )
        self.listen(Select.Changed, self.changed)

    def options(self) -> Iterable[tuple[str, object]]:
        """Each value on offer, with how it reads."""
        raise NotImplementedError

    def lists(self, value: object) -> bool:
        return any(value == choice for _, choice in self.offered)

    def value_text(self, value: object) -> str:
        for label, choice in self.offered:
            if value == choice:
                return label
        return super().value_text(value)

    def changed(self, message: Select.Changed) -> None:
        message.stop()
        if message.value is not Select.NULL:
            self.send(message.value)

    def paint(self) -> None:
        value = self.field.value
        with self.prevent(Select.Changed):
            self.value = value if self.lists(value) else Select.NULL


class ChoicesEditor(SelectEditor):
    shows = (AnnotationChoices,)

    @property
    def choices(self) -> AnnotationChoices:
        choices = declared_annotation_choices(self.field.annotation)
        assert choices is not None
        return choices

    def options(self) -> Iterable[tuple[str, object]]:
        return ((self.choices.label(choice), choice) for choice in self.choices.choices())


class EnumEditor(SelectEditor):
    shows = (Enum,)

    def options(self) -> Iterable[tuple[str, object]]:
        members: type[Enum] = resolve_annotated(self.field.annotation)  # type: ignore[assignment]
        return ((format_enum_display(member), member) for member in members)


class OptionalEditor(containers.VerticalGroup, ValueEditor):
    """A field that may hold nothing: a box says whether it holds a value, and the
    editor of that value is shown while it does."""

    shows = (Optional,)

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__()
        self.holds_value = Checkbox("Set", value=field.value is not None)
        self.member = ValueEditor.declared_for(field.member)
        self.member.display = field.value is not None
        self.holds_value.listen(Checkbox.Changed, self.held_changed)

    def compose(self) -> ComposeResult:
        yield self.holds_value
        yield self.member

    def held_changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.member.display = message.value
        if not message.value:
            self.send(None)

    def finish(self) -> None:
        self.member.finish()

    def value_text(self, value: object) -> str:
        return "not set" if value is None else self.member.value_text(value)

    def paint(self) -> None:
        held = self.field.value is not None
        with self.prevent(Checkbox.Changed):
            self.holds_value.value = held
        self.member.display = held
        self.member.paint()
