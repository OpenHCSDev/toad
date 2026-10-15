"""A form over an ObjectState, laid out the way formbridge reads its declarations."""

from __future__ import annotations

from collections.abc import Iterator

from formbridge.forms.parameter_form_service import (
    FormStructure,
    ParameterAnalysisInput,
    ParameterFormService,
)
from formbridge.forms.parameter_info_types import DirectDataclassInfo, GenericInfo
from objectstate import ObjectState
from python_introspect import UnifiedParameterAnalyzer, resolve_annotated
from textual import containers, events, lazy
from textual.app import ComposeResult
from textual.content import Content
from textual.widgets import Static

from toad.forms.declared_views import DeclaredField, DeclaredViews
from toad.forms.editors import ValueEditor
from toad.forms.field_path import FieldPath, label, steps


def form_structure(state: ObjectState) -> FormStructure:
    """What formbridge finds in the object the state holds.

    formbridge is given each field's type without its `Annotated` metadata:
    it does not see a nested dataclass through `Annotated` (formbridge issue #7).
    The views read labels, choices and bounds from the declaration itself.
    """
    held = state.object_instance
    declared = UnifiedParameterAnalyzer.analyze(held)
    return ParameterFormService().analyze_parameters(
        ParameterAnalysisInput(
            default_value={name: state.parameters[name] for name in declared},
            param_type={
                name: resolve_annotated(parameter.param_type)
                for name, parameter in declared.items()
            },
            field_id="",
            description=state.parameter_descriptions,
            parent_obj_type=type(held),
        )
    )


class FieldTitle(Static):
    DEFAULT_CSS = """
    FieldTitle {
        padding: 0 0 0 1;
        text-style: bold;
    }
    """


class FieldHelp(Static):
    DEFAULT_CSS = """
    FieldHelp {
        color: $text-muted;
        padding: 0 0 0 1;
        margin-bottom: 1;
    }
    """


class GroupTitle(Static):
    DEFAULT_CSS = """
    GroupTitle {
        padding: 0 0 0 1;
        color: $primary;
    }
    """


class FieldView(containers.VerticalGroup, DeclaredViews):
    """One parameter of a form, shown the way its formbridge kind asks for."""

    def __init__(self, field: DeclaredField, structure: FormStructure,
                 included: frozenset[FieldPath] | None = None) -> None:
        super().__init__()
        self.field = field

    @staticmethod
    def of(state: ObjectState, parent: FieldPath, structure: FormStructure,
           included: frozenset[FieldPath] | None = None) -> list[FieldView]:
        """A view for each parameter formbridge lists, in its order."""
        views = []
        for parameter in structure.parameters:
            path = getattr(parent, parameter.name)
            if included is None or path in included:
                field = DeclaredField.at(state, path)
                views.append(FieldView.showing(type(parameter).__mro__)(field, structure, included))
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

    DEFAULT_CSS = """
    ValueView {
        margin-bottom: 1;
        &:last-child {
            margin-bottom: 0;
        }
    }
    """

    CHANGED_MARK = " ●"

    def __init__(self, field: DeclaredField, structure: FormStructure,
                 included: frozenset[FieldPath] | None = None) -> None:
        super().__init__(field, structure, included)
        self.editor = ValueEditor.declared_for(field)
        self.title = FieldTitle(field.label)
        self.search_text = " ".join(label(step) for step in steps(field.path)).lower()

    def compose(self) -> ComposeResult:
        yield self.title
        yield FieldHelp(self.description())
        yield self.editor

    def description(self) -> Content:
        help = Content.from_markup(self.field.help)
        if not self.editor.states_default:
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

    DEFAULT_CSS = """
    GroupView {
        border: tall $secondary-muted;
        padding: 0 1;
        margin-bottom: 1;
        &:light {
            border: tall $foreground 20%;
        }
        &:focus-within {
            border: tall $secondary;
        }
        &:last-child {
            margin-bottom: 0;
        }
    }
    """

    def __init__(self, field: DeclaredField, structure: FormStructure,
                 included: frozenset[FieldPath] | None = None) -> None:
        super().__init__(field, structure, included)
        name = str(field.path).rpartition(".")[2]
        self.parts = FieldView.of(field.state, field.path, structure.nested_forms[name], included)

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


class FormView(containers.VerticalScroll, can_focus=False):
    """Every field of the object an ObjectState holds, edited in place.

    The form holds no values. An edit goes to the state; the state says which
    fields changed and the form repaints those, and marks the ones that differ
    from what was last saved. The fields are mounted over several frames, so a
    long form does not hold up the frame it opens in.
    """

    DEFAULT_CSS = """
    FormView {
        layout: stream;
        overflow: hidden scroll;
    }
    """

    def __init__(self, state: ObjectState, *, paths: tuple[FieldPath, ...] | None = None) -> None:
        super().__init__()
        self.state = state
        included = (None if paths is None else
                    frozenset(step for path in paths for step in steps(path)))
        self.parts = FieldView.of(
            state, FieldPath(type(state.object_instance)), form_structure(state), included
        )
        self.values = {
            str(view.field.path): view for part in self.parts for view in part.values()
        }
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
