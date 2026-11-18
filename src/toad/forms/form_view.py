"""A form over an ObjectState, laid out the way formbridge reads its declarations."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator

from formbridge.forms.declared_fields import DeclaredField
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from formbridge.forms.value_editing import ValueEditing
from objectstate import ObjectState
from rich.style import Style
from textual import containers, events, lazy, on
from textual.app import ComposeResult
from textual.content import Content
from textual.css._style_properties import Edges
from textual.geometry import Spacing
from textual.layouts.stream import StreamLayout
from textual.view import (
    AUTO,
    FocusWithinView,
    WidgetView,
)
from textual.widgets import Static
from ui_theme.scheme import (
    BackgroundColour,
    ErrorColour,
    ForegroundColour,
    MutedColour,
    PrimaryColour,
    SecondaryColour,
)

from toad.form_family import FieldForm, FieldViews, GroupFields, ValueFields
from toad.forms.editors import ValueEditor


class FieldTitle(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)
    text_style = Style(bold=True)


class FieldHelp(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)
    margin = Spacing(0, 0, 1, 0)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(MutedColour)


class FieldRefusal(FieldHelp):
    @property
    def paint_foreground(self):
        return self.app.colours.colour(ErrorColour)


class GroupTitle(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(PrimaryColour)


class FieldView(FieldViews, WidgetView, containers.VerticalGroup):
    """One parameter of a form, shown the way its formbridge kind asks for."""

    def __init__(self, field: DeclaredField) -> None:
        super().__init__()
        self.field = field

    @property
    def margin(self) -> Spacing:
        return Spacing(0, 0, 0 if self.last_child else 1, 0)

    @classmethod
    def family(cls):
        return FieldView

    def show_field(self, shown: bool) -> None:
        self.display = shown

    @abstractmethod
    def values(self) -> Iterator[ValueView]:
        """The views below this one that hold a single value."""


class ValueView(ValueFields, FieldView, shows=(ParameterInfo,)):
    """A field with one value: its label, its help and the editor for its kind."""

    editor: ValueEditor

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.editor = self.editor_for(ValueEditor)
        self.title = FieldTitle(field.label)
        self.refusal = FieldRefusal("", markup=False)
        self.refusal.display = False

    def compose(self) -> ComposeResult:
        yield self.title
        yield FieldHelp(self.description())
        yield self.editor
        yield self.refusal

    @on(ValueEditor.Feedback)
    def show_feedback(self, message: ValueEditor.Feedback) -> None:
        message.stop()
        self.refusal.update(message.text)
        self.refusal.display = bool(message.text)

    def description(self) -> Content:
        help = Content.from_markup(self.field.help)
        if accepts := self.accepts_text:
            help = Content.assemble(help, (f"\n{accepts}", "$text-secondary"))
        return Content.assemble(help, (self.editor.default_note(), "$text-secondary"))

    def mark(self, changed: bool) -> None:
        """Say on the title whether the value differs from the saved one."""
        self.title.update(Content.assemble(self.field.label, (self.changed_mark(changed), "$text-warning")))


class GroupView(GroupFields, FocusWithinView, FieldView, shows=(DirectDataclassInfo,)):
    """A nested dataclass: a heading and the views of its fields."""

    padding = Spacing(0, 1, 0, 1)

    @property
    def border(self) -> Edges:
        colours = self.app.colours
        colour = (colours.colour(SecondaryColour) if self.has_focus_within else
                  colours.mixed(BackgroundColour, SecondaryColour, 0.3) if colours.scheme.dark else
                  colours.colour(ForegroundColour).multiply_alpha(0.2))
        return Edges(*(("tall", colour),) * 4)

    field_family = FieldView

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.build_parts()

    def compose(self) -> ComposeResult:
        yield GroupTitle(self.field.label)
        yield FieldHelp(Content.from_markup(self.field.help))
        yield from self.parts


class FormView(FieldForm, WidgetView, containers.VerticalScroll, can_focus=False):
    """Every field of the object an ObjectState holds, edited in place.

    The form holds no values. An edit goes to the state; the state says which
    fields changed and the form repaints those, and marks the ones that differ
    from what was last saved. Subscription and change algorithms are inherited
    from FollowingForm; native mounting and painting stay here.
    """

    field_family = FieldView
    parts: list[FieldView]
    DEFAULT_LAYOUT = StreamLayout
    height = None
    overflow_y = "scroll"

    def __init__(self, state: ObjectState, parts: list[FieldView]) -> None:
        super().__init__()
        self.state = state
        self.parts = parts
        self.build_index()
        self.listen(events.Mount, self._mount_follow)
        self.listen(events.Unmount, self._unmount_follow)

    def _mount_follow(self, event: events.Mount) -> None:
        lazy.Reveal.reveal(self, list(self.parts))
        self.follow_state()

    def _unmount_follow(self, event: events.Unmount) -> None:
        self.leave_state()

    def repaint_editor(self, editor: ValueEditing) -> None:
        ve: ValueEditor = editor  # type: ignore[assignment]
        if ve.is_mounted:
            ve.paint_value()

class InlineFormView(FormView):
    """An intrinsically sized form inside a bounded dialog panel."""

    height = AUTO
