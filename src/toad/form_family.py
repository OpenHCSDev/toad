"""The form family both frontends inherit: which view shows a declared field, which editor
edits it, how a form splits into pages, searches and marks changes, and how an editor reads
its text back. Textual's `toad.forms` and Qt's `toad.qt.settings_screen` add only native
widgets, painting and event wiring on top of these parents and formbridge's.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from typing import ClassVar

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import DeclaredField, DeclaredViews, FormPage, form_pages
from formbridge.forms.form_following import FollowedFieldView, FollowedValueView, FollowingForm
from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.value_editing import ControlConstruction, LineEditing, SelectEditing, ValueEditing
from objectstate import ObjectState
from python_introspect import resolve_annotated
from ui_theme.catalog import SCHEMES
from ui_theme.scheme import PrimaryColour, ThemeColour


# The editors.

class FieldEditing(ControlConstruction):
    """An editor bound to one declared field, painted from the field's state.

    A field that holds no value of its own but resolves one (an inherited default) is
    previewed: the editor shows that value muted and an edit replaces it.
    """

    @property
    def previewing(self) -> bool:
        return self.field.state.parameters[self.field.path.value] is None and self.field.value is not None

    @abstractmethod
    def paint(self) -> None:
        """Paint the native control from the field's state, without echoing a change."""


class LineFieldEditing(LineEditing, FieldEditing):
    """One line of text, read as the field's type when the user finishes with it."""

    def current_text(self) -> str:
        return "" if self.previewing else self.value_text(self.field.value)

    def placeholder_text(self) -> str:
        return self.value_text(self.field.value) if self.previewing else self.field.placeholder

    def read(self, text: str) -> object:
        return resolve_annotated(self.field.annotation)(text)  # type: ignore[operator]

    def commit(self, text: str) -> None:
        """Send the typed text as the field's value; an unchanged text sends nothing."""
        if text == self.current_text():
            return
        try:
            value = self.read(text)
        except ValueError as error:
            self.refuse(error)
        else:
            self.send(value)


class StructuredFieldEditing(LineFieldEditing):
    """A JSON value checked against the complete declared collection type."""

    def value_text(self, value: object) -> str:
        return json.dumps(FieldCodec.encode(value), ensure_ascii=False)

    def read(self, text: str) -> object:
        return FieldCodec.decode(self.field.annotation, FieldCodec.parse(text.encode()))


class SelectFieldEditing(SelectEditing, FieldEditing):
    """One of a list of values; a value not on the list shows as its own text."""

    def shows_choice(self, value: object) -> bool:
        """Whether the native select shows this value as its chosen option."""
        return not self.previewing and self.lists(value)


class SchemeChoosing(SelectEditing):
    """A colour scheme's name, offered from the schemes the running frontend has."""

    def scheme_names(self) -> Iterable[str]:
        """ui_theme's catalog; a frontend that adds runtime schemes (pywal) overrides this."""
        return (scheme.name for scheme in SCHEMES)

    def options(self) -> Iterable[tuple[str, object]]:
        return ((name, name) for name in self.scheme_names())


# The field views.

class FieldViews(FollowedFieldView, DeclaredViews):
    """A family of views, each over one ObjectState field, chosen by formbridge's kind for it.

    Each frontend root names itself as `family()`; a sub-family (an object form's views)
    names itself, so one family's lookup never returns another's member.
    """

    field_type: ClassVar[type[DeclaredField]] = DeclaredField
    field: DeclaredField

    @classmethod
    @abstractmethod
    def family(cls) -> type[FieldViews]:
        """The root of the family this view belongs to."""

    @classmethod
    def members(cls):
        return (member for member in super().members() if member.family() is cls.family())

    @classmethod
    def admits(cls, field: DeclaredField) -> bool:
        return True

    @classmethod
    def from_field(cls, field: DeclaredField):
        """The field provider supplies the declaration used to select its presentation."""
        from formbridge.forms.parameter_info_types import ParameterInfo

        declaration = field.declaration
        parameter = ParameterInfo.create(
            name=declaration.name, param_type=field.annotation,
            current_value=None, default_value=declaration.default_value,
            description=declaration.description, is_required=declaration.is_required)
        return cls.showing(type(parameter).__mro__)(field)

    @classmethod
    def of(cls, state: ObjectState, parent: str = "") -> list:
        """Show ObjectState's direct children; formbridge supplies each field's kind.

        ObjectState already extracted this topology. Reading it does not rebuild
        a second form tree or re-analyze the held object's values.
        """
        return [cls.part(shown) for shown in cls.shown(state, parent)]

    @classmethod
    def shown(cls, state: ObjectState, parent: str = "") -> list[tuple]:
        """The direct children this family shows, as (parameter, field), with no view built:
        knowing which fields a form holds is cheap, and building their views is not."""
        return [(parameter, field)
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)
                if cls.admits(field := cls.field_type(state, path))]

    @classmethod
    def part(cls, shown: tuple):
        """The view of one shown field."""
        parameter, field = shown
        return cls.showing(type(parameter).__mro__)(field)

    @abstractmethod
    def show_field(self, shown: bool) -> None:
        """Show or hide this view natively."""


class ValueFields(FollowedValueView, FieldViews):
    """A field with one value: its label, its help and the editor for its kind."""

    CHANGED_MARK: ClassVar[str] = " ●"

    def editor_for(self, editors: type[ValueEditing]) -> ValueEditing:
        """This field's editor from a frontend's editor family."""
        return editors.declared_for(self.field)

    @property
    def accepts_text(self) -> str:
        """The declared bounds as help: `accepts: >= 1`; empty when unbounded."""
        bounds = self.field.bounds_text
        return f"accepts: {bounds}" if bounds else ""

    def changed_mark(self, changed: bool) -> str:
        """What follows the label when the value differs from the saved one."""
        return self.CHANGED_MARK if changed else ""

    def filter(self, term: str) -> bool:
        shown = term in self.field.search_text
        self.show_field(shown)
        return shown


class ObjectValueFields(ValueFields):
    """One setting of a viewed object (an `ObjectSettingField`): whether this object
    overrides it, where its value comes from, and resetting it. Textual's object form
    and Qt's both inherit this; each draws the source line and a Reset control."""

    reset_label: ClassVar[str] = "Reset"

    def overridden(self) -> bool:
        """This object holds its own value, where the setting admits one."""
        return self.field.allows_override and self.field.state.parameters[self.field.path.value] is not None

    def source_text(self) -> str:
        if self.overridden():
            return "Override for this object"
        return "Inherited from global defaults" if self.field.allows_override else "Global setting · applies to every view"

    def source_detail(self) -> str:
        """Which declaration and scope the shown value comes from."""
        scope, owner = self.field.state.get_provenance(self.field.path.value)
        return f"{owner.__module__}.{owner.__qualname__} · {scope or 'global'}"

    def reset_field(self) -> None:
        """Back to the parameter's own signature default, refusal cleared."""
        self.field.reset()
        self.editor.clear_feedback()


class GroupFields(FieldViews):
    """A nested dataclass: a heading and the views of its fields."""

    heading_colour: ClassVar[type[ThemeColour]] = PrimaryColour
    field_family: ClassVar[type[FieldViews]]
    parts: list

    def build_parts(self) -> None:
        self.parts = self.field_family.of(self.field.state, self.field.path.value)

    def values(self) -> Iterator[FollowedValueView]:
        for part in self.parts:
            yield from part.values()

    def filter(self, term: str) -> bool:
        shown = any([part.filter(term) for part in self.parts])
        self.show_field(shown)
        return shown


# The form.

class FieldForm(FollowingForm):
    """Every shown field of an ObjectState, on one form or split into its declared pages."""

    field_family: ClassVar[type[FieldViews]]

    @classmethod
    def whole(cls, state: ObjectState):
        """Every shown field of the state on one form."""
        return cls(state, cls.field_family.of(state))

    @classmethod
    def pages(cls, state: ObjectState) -> dict[FormPage, Callable[[], FieldForm]]:
        """Each page the top-level fields declare, in declaration order, and how to build its
        form: a page's views are built when it is shown (`LazyPages`), not when it is listed."""
        shown = {field.path: (parameter, field) for parameter, field in cls.field_family.shown(state)}
        return {page: partial(cls.page_form, state, tuple(shown[path] for path in paths))
                for page, paths in form_pages(state, shown).items()}

    @classmethod
    def page_form(cls, state: ObjectState, shown: tuple[tuple, ...]) -> FieldForm:
        return cls(state, [cls.field_family.part(field) for field in shown])

    def filter(self, term: str) -> None:
        self.filter_parts(term)
