"""A form over an ObjectState, laid out the way formbridge reads its declarations."""

from __future__ import annotations

from collections.abc import Iterator

from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.parameter_info_types import DirectDataclassInfo, ParameterInfo
from objectstate import ObjectState
from textual import containers, events, lazy
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static
from textual.css._style_properties import Edges
from textual.geometry import Spacing
from textual.layouts.stream import StreamLayout
from rich.style import Style
from ui_theme.scheme import BackgroundColour, ForegroundColour, MutedColour, PrimaryColour, SecondaryColour

from formbridge.forms.declared_fields import DeclaredField, DeclaredViews, FormPage, form_pages
from toad.forms.editors import ValueEditor
from toad.widget_view import AUTO, FocusWithinView, WidgetView


class FieldTitle(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)
    text_style = Style(bold=True)


class FieldHelp(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)
    margin = Spacing(0, 0, 1, 0)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(MutedColour)


class GroupTitle(WidgetView, Static):
    padding = Spacing(0, 0, 0, 1)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(PrimaryColour)


class FieldView(WidgetView, containers.VerticalGroup, DeclaredViews):
    """One parameter of a form, shown the way its formbridge kind asks for."""

    def __init__(self, field: DeclaredField) -> None:
        super().__init__()
        self.field = field

    @property
    def margin(self) -> Spacing:
        return Spacing(0, 0, 0 if self.last_child else 1, 0)

    @staticmethod
    def of(state: ObjectState, parent: str = "") -> list[FieldView]:
        """Show ObjectState's direct children; FormBridge supplies each field's kind.

        ObjectState already extracted this topology. Reading it does not rebuild
        a second form tree or re-analyze the held object's values.
        """
        return [FieldView.showing(type(parameter).__mro__)(DeclaredField(state, path))
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)]

    def values(self) -> Iterator[ValueView]:
        """The views below this one that hold a single value."""
        raise NotImplementedError

    def filter(self, term: str) -> bool:
        """Show this view only if it matches a search; say whether it is shown."""
        raise NotImplementedError


class ValueView(FieldView):
    """A field with one value: its label, its help and the editor for its kind."""

    shows = (ParameterInfo,)

    CHANGED_MARK = " ●"

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.editor = ValueEditor.declared_for(field)
        self.title = FieldTitle(field.label)

    def compose(self) -> ComposeResult:
        yield self.title
        yield FieldHelp(self.description())
        yield self.editor

    def description(self) -> Content:
        help = Content.from_markup(self.field.help)
        if bounds := self.field.bounds_text:
            help = Content.assemble(help, (f"\naccepts: {bounds}", "$text-secondary"))
        return Content.assemble(help, (self.editor.default_note(), "$text-secondary"))

    def values(self) -> Iterator[ValueView]:
        yield self

    def filter(self, term: str) -> bool:
        self.display = term in self.field.search_text
        return bool(self.display)

    def mark(self, changed: bool) -> None:
        """Say on the title whether the value differs from the saved one."""
        self.title.update(
            Content.assemble(self.field.label, (self.CHANGED_MARK, "$text-warning"))
            if changed
            else self.field.label
        )


class GroupView(FocusWithinView, FieldView):
    """A nested dataclass: a heading and the views of its fields."""

    shows = (DirectDataclassInfo,)

    padding = Spacing(0, 1, 0, 1)

    @property
    def border(self) -> Edges:
        colours = self.app.colours
        colour = (colours.colour(SecondaryColour) if self.has_focus_within else
                  colours.mixed(BackgroundColour, SecondaryColour, 0.3) if colours.scheme.dark else
                  colours.colour(ForegroundColour).multiply_alpha(0.2))
        return Edges(*(("tall", colour),) * 4)

    def __init__(self, field: DeclaredField) -> None:
        super().__init__(field)
        self.parts = FieldView.of(field.state, field.path.value)

    def compose(self) -> ComposeResult:
        yield GroupTitle(self.field.label)
        yield FieldHelp(Content.from_markup(self.field.help))
        yield from self.parts

    def values(self) -> Iterator[ValueView]:
        for part in self.parts:
            yield from part.values()

    def filter(self, term: str) -> bool:
        self.display = any([part.filter(term) for part in self.parts])
        return bool(self.display)


class FormView(WidgetView, containers.VerticalScroll, can_focus=False):
    """Every field of the object an ObjectState holds, edited in place.

    The form holds no values. An edit goes to the state; the state says which
    fields changed and the form repaints those, and marks the ones that differ
    from what was last saved. The fields are mounted over several frames, so a
    long form does not hold up the frame it opens in.
    """

    DEFAULT_LAYOUT = StreamLayout
    height = None
    overflow_y = "scroll"

    def __init__(self, state: ObjectState, parts: list[FieldView]) -> None:
        super().__init__()
        self.state = state
        self.parts = parts
        self.values = {
            view.field.path.value: view for part in self.parts for view in part.values()
        }
        self.listen(events.Mount, self.follow_state)
        self.listen(events.Unmount, self.leave_state)

    @classmethod
    def whole(cls, state: ObjectState) -> FormView:
        """Every shown field of the state on one form."""
        return cls(state, FieldView.of(state))

    @classmethod
    def pages(cls, state: ObjectState) -> dict[FormPage, FormView]:
        """One form per page the top-level fields declare, in declaration order."""
        parts = {part.field.path: part for part in FieldView.of(state)}
        return {page: cls(state, [parts[path] for path in paths])
                for page, paths in form_pages(state, parts).items()}

    def follow_state(self, event: events.Mount) -> None:
        lazy.Reveal.reveal(self, list(self.parts))
        self.state.on_resolved_changed(self.values_changed)
        self.state.on_state_changed(self.marks_changed)
        self.marks_changed(self.state.dirty_fields)

    def leave_state(self, event: events.Unmount) -> None:
        self.state.off_resolved_changed(self.values_changed)
        self.state.off_state_changed(self.marks_changed)

    def values_changed(self, paths: set[str]) -> None:
        for path in paths & self.values.keys():
            self.values[path].editor.paint()

    def marks_changed(self, paths: set[str]) -> None:
        differ = self.state.dirty_fields
        for path in paths & self.values.keys():
            self.values[path].mark(path in differ)

    def finish(self) -> None:
        """Send every edit the user has typed but not left yet."""
        for view in self.values.values():
            view.editor.finish()

    def filter(self, term: str) -> None:
        """Show only the fields whose labels contain the term."""
        for part in self.parts:
            part.filter(term.lower())


class InlineFormView(FormView):
    """An intrinsically sized form inside a bounded dialog panel."""

    height = AUTO
