"""A form over an ObjectState, laid out the way formbridge reads its declarations."""

from __future__ import annotations

from collections.abc import Iterator

from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.parameter_info_types import DirectDataclassInfo, GenericInfo
from objectstate import DottedFieldPath, ObjectState
from textual import containers, events, lazy
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static
from textual.css._style_properties import Edges
from textual.geometry import Spacing
from textual.layouts.stream import StreamLayout
from rich.style import Style
from ui_theme.scheme import BackgroundColour, ForegroundColour, MutedColour, PrimaryColour, SecondaryColour

from toad.forms.declared_views import DeclaredField, DeclaredViews
from toad.forms.editors import ValueEditor
from toad.forms.field_path import FieldPath
from toad.forms.presentation import AUTO, FormPart


class FieldTitle(FormPart, Static):
    padding = Spacing(0, 0, 0, 1)
    text_style = Style(bold=True)


class FieldHelp(FormPart, Static):
    padding = Spacing(0, 0, 0, 1)
    margin = Spacing(0, 0, 1, 0)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(MutedColour)


class GroupTitle(FormPart, Static):
    padding = Spacing(0, 0, 0, 1)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(PrimaryColour)


class FieldView(FormPart, containers.VerticalGroup, DeclaredViews):
    """One parameter of a form, shown the way its formbridge kind asks for."""

    def __init__(self, field: DeclaredField,
                 included: frozenset[DottedFieldPath] | None = None) -> None:
        super().__init__()
        self.field = field

    @property
    def margin(self) -> Spacing:
        return Spacing(0, 0, 0 if self.last_child else 1, 0)

    @staticmethod
    def of(state: ObjectState, parent: str = "",
           included: frozenset[DottedFieldPath] | None = None) -> list[FieldView]:
        """Show ObjectState's direct children; FormBridge supplies each field's kind.

        ObjectState already extracted this topology. Reading it does not rebuild
        a second form tree or re-analyze the held object's values.
        """
        views = []
        for path, parameter in ParameterFormService().parameters_for_state(state, parent):
            if included is None or path in included:
                field = DeclaredField(state, path)
                views.append(FieldView.showing(type(parameter).__mro__)(field, included))
        return views

    def values(self) -> Iterator[ValueView]:
        """The views below this one that hold a single value."""
        raise NotImplementedError

    def filter(self, term: str) -> bool:
        """Show this view only if it matches a search; say whether it is shown."""
        raise NotImplementedError


class ValueView(FieldView):
    """A field with one value: its label, its help and the editor for its kind."""

    shows = (GenericInfo,)

    CHANGED_MARK = " ●"

    def __init__(self, field: DeclaredField,
                 included: frozenset[DottedFieldPath] | None = None) -> None:
        super().__init__(field, included)
        self.editor = ValueEditor.declared_for(field)
        self.title = FieldTitle(field.label)
        self.search_text = " ".join(
            DeclaredField(field.state, step).label
            for step in field.state.parameter_structure.ancestors(field.path)
        ).lower()

    def compose(self) -> ComposeResult:
        yield self.title
        yield FieldHelp(self.description())
        yield self.editor

    def description(self) -> Content:
        help = Content.from_markup(self.field.help)
        if not self.editor.states_default or not self.field.has_default:
            return help
        default = self.editor.value_text(self.field.default)
        return Content.assemble(help, (f"\ndefault: {default}", "$text-secondary"))

    def values(self) -> Iterator[ValueView]:
        yield self

    def filter(self, term: str) -> bool:
        self.display = term in self.search_text
        return term in self.search_text

    def mark(self, changed: bool) -> None:
        """Say on the title whether the value differs from the saved one."""
        self.title.update(
            Content.assemble(self.field.label, (self.CHANGED_MARK, "$text-warning"))
            if changed
            else self.field.label
        )


class GroupView(FieldView):
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

    def __init__(self, field: DeclaredField,
                 included: frozenset[DottedFieldPath] | None = None) -> None:
        super().__init__(field, included)
        self.parts = FieldView.of(field.state, field.path.value, included)

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


class FormView(FormPart, containers.VerticalScroll, can_focus=False):
    """Every field of the object an ObjectState holds, edited in place.

    The form holds no values. An edit goes to the state; the state says which
    fields changed and the form repaints those, and marks the ones that differ
    from what was last saved. The fields are mounted over several frames, so a
    long form does not hold up the frame it opens in.
    """

    DEFAULT_LAYOUT = StreamLayout
    height = None
    overflow_y = "scroll"

    def __init__(self, state: ObjectState, *, paths: tuple[FieldPath, ...] | None = None,
                 focus: DottedFieldPath | None = None) -> None:
        super().__init__()
        self.state = state
        included = (None if paths is None else frozenset(
            step for path in paths
            for step in state.parameter_structure.ancestors(path.bind(state).path)
        ))
        self.parts = FieldView.of(state, included=included)
        self.values = {
            view.field.path.value: view for part in self.parts for view in part.values()
        }
        if focus is not None:
            editor = self.values[focus.value].editor
            editor.listen(events.Mount, lambda _: editor.focus())
        self.listen(events.Mount, self.follow_state)
        self.listen(events.Unmount, self.leave_state)

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
