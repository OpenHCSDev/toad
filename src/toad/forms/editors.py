"""One control per kind of value, chosen by what the field declares."""

from __future__ import annotations

from abc import abstractmethod
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
from textual import containers, on, work
from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import var
from textual.validation import Function
from textual.geometry import Spacing
from textual.css.scalar import Scalar
from textual.color import TRANSPARENT
from textual.widget import Widget
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static, TextArea
from textual.widgets._input import InputType
from textual.widgets.select import NoSelection

from toad.forms.declared_views import DeclaredField, DeclaredViews, UnionMembers, declarations
from toad.forms.kinds import Multiline
from toad.forms.presentation import FormCheckbox, FormInput, FormSelectCurrent, FramedControl
from toad.widget_view import WidgetView
from toad.tone_paint import UntintedTonePaint

if TYPE_CHECKING:
    from agent_comms.field_codec import MemberSelection

    EditorWidget = Widget
else:
    EditorWidget = object


class ValueEditor(DeclaredViews, EditorWidget):
    """A control that shows one field's value and sends the user's edits to the state.

    The value lives in the ObjectState: the control is painted from it. Only
    transient validation feedback lives here. The editor binds the field before the native
    control is initialized: `class BoolEditor(ValueEditor, Checkbox)`.
    """

    states_default: ClassVar[bool] = True
    """Whether the field's help should end with its default value."""

    field: DeclaredField
    feedback: var[str] = var("", init=False)

    class Feedback(Message):
        """Transient validation text for the field's own view, never a crash log."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, field: DeclaredField) -> None:
        self.field = field
        super().__init__(**self.control_arguments())
        self.bind_control()

    def control_arguments(self) -> dict[str, object]:
        """Arguments for the native control; containers need no initial value."""
        return {}

    def bind_control(self) -> None:
        """Connect the native control's edits after it has been initialized."""
        raise NotImplementedError

    @classmethod
    def declared_for(cls, field: DeclaredField) -> ValueEditor:
        return cls.showing(declarations(field.annotation))(field)

    def paint(self) -> None:
        """Paint the control from the state."""
        raise NotImplementedError

    def finish(self) -> None:
        """Send an edit the user has not finished yet. Most controls have none."""

    @abstractmethod
    def commit(self) -> None:
        """Explicitly supply the displayed input, even when it is unchanged."""

    def value_text(self, value: object) -> str:
        """How a value of this field reads."""
        return self.field.placeholder if value is None else str(value)

    def send(self, value: object) -> None:
        try:
            self.field.edit(value)
        except (TypeError, ValueError) as error:
            self.refuse(error)
        else:
            self.feedback = ""

    def refuse(self, error: Exception) -> None:
        self.feedback = str(error)
        self.paint()

    def watch_feedback(self, text: str) -> None:
        self.post_message(self.Feedback(text))


class BoolEditor(ValueEditor, FormCheckbox):
    shows = (bool,)

    def control_arguments(self) -> dict[str, object]:
        return {"value": bool(self.field.value)}

    def bind_control(self) -> None:
        self.listen(Checkbox.Changed, self.changed)

    def changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.send(message.value)

    def commit(self) -> None:
        self.send(self.value)

    def paint(self) -> None:
        with self.prevent(Checkbox.Changed):
            self.value = bool(self.field.value)


class LineEditor(ValueEditor, FormInput):
    """One line of text, read as the field's type when the user leaves it or presses enter."""

    accepts: ClassVar[InputType]

    def control_arguments(self) -> dict[str, object]:
        return {
            "value": self.value_text(self.field.value),
            "type": self.accepts,
            "validators": [Function(self.acceptable)],
        }

    def bind_control(self) -> None:
        self.listen(Input.Blurred, self.finished)
        self.listen(Input.Submitted, self.finished)

    def read(self, text: str) -> object:
        return resolve_annotated(self.field.annotation)(text)  # type: ignore[operator]

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
        self.commit()

    def commit(self) -> None:
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


class MultilineEditor(ValueEditor, UntintedTonePaint, FramedControl, TextArea):
    shows = (Multiline,)
    height = Scalar.from_number(10)
    padding = Spacing(0, 1, 0, 1)

    states_default = False

    def control_arguments(self) -> dict[str, object]:
        return {"text": str(self.field.value or "")}

    def bind_control(self) -> None:
        self.listen(TextArea.Changed, self.changed)

    def changed(self, message: TextArea.Changed) -> None:
        message.stop()
        self.send(self.text)

    def commit(self) -> None:
        self.send(self.text)

    def paint(self) -> None:
        value = str(self.field.value or "")
        if self.text != value:
            with self.prevent(TextArea.Changed):
                self.load_text(value)


class SelectEditor(ValueEditor, WidgetView, Select[object]):
    """One of a list of values. A value that is not on the list shows as its own text."""

    CURRENT = FormSelectCurrent

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        if self.is_mounted:
            self.query_one(FormSelectCurrent).refresh_paint()

    def control_arguments(self) -> dict[str, object]:
        options = tuple(self.options())
        value = self.field.value
        listed = any(value == choice for _, choice in options)
        return {
            "options": options,
            "value": value if listed else Select.NULL,
            "allow_blank": not listed,
            "prompt": self.field.placeholder if value is None else str(value),
        }

    def bind_control(self) -> None:
        self.listen(Select.Changed, self.changed)

    def options(self) -> Iterable[tuple[str, object]]:
        """Each value on offer, with how it reads."""
        raise NotImplementedError

    def lists(self, value: object) -> bool:
        return value in self._legal_values

    def value_text(self, value: object) -> str:
        for label, choice in self._options:
            if value == choice:
                return label
        return super().value_text(value)

    def changed(self, message: Select.Changed) -> None:
        message.stop()
        if message.value is not Select.NULL:
            self.send(message.value)

    def commit(self) -> None:
        if self.value is not Select.NULL:
            self.send(self.value)

    def paint(self) -> None:
        value = self.field.value
        with self.prevent(Select.Changed):
            self.prompt = self.value_text(value)
            self.value = value if self.lists(value) else Select.NULL


class ChoicesEditor(SelectEditor):
    shows = (AnnotationChoices,)

    def paint(self) -> None:
        with self.prevent(Select.Changed):
            self.set_options(self.options())
            super().paint()

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


class OptionalEditor(ValueEditor, WidgetView, containers.VerticalGroup):
    """A field that may hold nothing: a box says whether it holds a value, and the
    editor of that value is shown while it does."""

    shows = (Optional,)

    def bind_control(self) -> None:
        self.holds_value = FormCheckbox("Set", value=self.field.value is not None)
        self.member = ValueEditor.declared_for(self.field.member)
        self.member.listen(ValueEditor.Feedback, self.member_feedback)
        self.member.display = self.field.value is not None
        self.holds_value.listen(Checkbox.Changed, self.held_changed)

    def compose(self) -> ComposeResult:
        yield self.holds_value
        yield self.member

    def member_feedback(self, message: ValueEditor.Feedback) -> None:
        message.stop()
        self.feedback = message.text

    def held_changed(self, message: Checkbox.Changed) -> None:
        message.stop()
        self.member.display = message.value
        if message.value:
            self.member.commit()
        else:
            self.member.set_reactive(ValueEditor.feedback, "")
            self.send(None)

    def finish(self) -> None:
        if self.holds_value.value:
            self.member.finish()

    def commit(self) -> None:
        if self.holds_value.value:
            self.member.commit()
        else:
            self.send(None)

    def value_text(self, value: object) -> str:
        return "not set" if value is None else self.member.value_text(value)

    def paint(self) -> None:
        held = self.field.value is not None
        with self.prevent(Checkbox.Changed):
            self.holds_value.value = held
        self.member.display = held
        self.member.paint()


class UnionEditor(ValueEditor, Button):
    """Choose and edit a declared member without changing the parent until Apply."""

    shows = (UnionMembers,)

    @property
    def members(self) -> UnionMembers:
        metadata = self.field.metadata(UnionMembers)
        assert metadata is not None
        return metadata

    def bind_control(self) -> None:
        self.paint()

    def value_text(self, value: object) -> str:
        return self.members.selected(value).label

    def paint(self) -> None:
        self.label = self.value_text(self.field.value)

    def commit(self) -> None:
        self.send(self.field.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.choose()

    @work(exclusive=True)
    async def choose(self) -> None:
        dialog = self.members.dialog(self.field)
        try:
            await self.app.push_screen_wait(dialog)
        finally:
            if dialog.is_attached:
                dialog.dismiss()
        if self.is_attached:
            self.paint()


class UnionMemberDialog(ModalScreen[None]):
    """One pending member transaction; its ObjectState never holds a valid parent."""

    DEFAULT_CSS = '''
    UnionMemberDialog { align: center middle; background: $background 40%; }
    UnionMemberDialog #union-box { width: 68; max-width: 95%; height: 90%;
        background: $surface; border: solid $primary; padding: 1 2; }
    UnionMemberDialog #union-body { height: 1fr; }
    UnionMemberDialog #union-buttons { height: 3; }
    '''

    def __init__(self, field: DeclaredField, members: UnionMembers) -> None:
        from toad.forms.form_view import InlineFormView

        super().__init__()
        self.field, self.members = field, members
        choice = members.selected(field.value)
        self.selector: Select[MemberSelection] = Select(
            [(member.label, member) for member in members.choices()],
            value=choice, allow_blank=False, id='union-member',
        )
        self.draft = members.draft(choice, field.value)
        self.form = InlineFormView(self.draft.state)
        self.body = containers.VerticalScroll(self.form, id='union-body')
        self.feedback = Static('', markup=False)
        self.apply_button = Button('Apply', id='union-apply', variant='primary', disabled=True)

    def compose(self) -> ComposeResult:
        with containers.Vertical(id='union-box'):
            yield Static(self.field.label, markup=False)
            yield self.selector
            yield self.body
            yield self.feedback
            with containers.Horizontal(id='union-buttons'):
                yield self.apply_button
                yield Button('Cancel', id='union-cancel')

    def on_mount(self) -> None:
        self.draft.state.on_resolved_changed(self.changed)
        self.validate_draft()

    def on_unmount(self) -> None:
        self.draft.state.off_resolved_changed(self.changed)

    def changed(self, paths: set[str]) -> None:
        self.validate_draft()

    def validate_draft(self) -> None:
        try:
            self.draft.complete()
        except self.draft.refusal as error:
            self.feedback.update(str(error))
            self.apply_button.disabled = True
        else:
            self.feedback.update('')
            self.apply_button.disabled = False

    @on(Select.Changed, '#union-member')
    async def select_member(self, event: Select.Changed) -> None:
        from toad.forms.form_view import InlineFormView

        event.stop()
        choice = self.selector.value
        if isinstance(choice, NoSelection):
            raise ValueError('A union selector requires a declared selection')
        if choice == self.draft.selection:
            return
        self.apply_button.disabled = True
        self.draft.state.off_resolved_changed(self.changed)
        await self.form.remove()
        if not self.is_attached:
            return
        self.draft = self.members.draft(choice, self.field.value)
        self.form = InlineFormView(self.draft.state)
        await self.body.mount(self.form)
        self.draft.state.on_resolved_changed(self.changed)
        self.validate_draft()

    @on(Button.Pressed, '#union-apply')
    def apply_member(self, event: Button.Pressed) -> None:
        event.stop()
        self.form.finish()
        try:
            value = self.draft.complete()
        except self.draft.refusal as error:
            self.feedback.update(str(error))
            self.apply_button.disabled = True
            return
        self.field.edit(value)
        self.dismiss()

    @on(Button.Pressed, '#union-cancel')
    def cancel_member(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()
