"""The form family both frontends inherit: which view shows a declared field, which editor
edits it, how a form splits into pages, searches and marks changes, and how an editor reads
its text back. Textual's `toad.forms` and Qt's `toad.qt.settings_screen` add only native
widgets, painting and event wiring on top of these parents and formbridge's.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterable, Iterator
from typing import ClassVar

from agent_comms.nominal.field_codec import FieldCodec
from formbridge.forms.declared_fields import DeclaredField, DeclaredViews, FormPage, form_pages
from formbridge.forms.form_following import FollowedFieldView, FollowedValueView, FollowingForm
from formbridge.forms.parameter_form_service import ParameterFormService
from formbridge.forms.value_editing import ControlConstruction, LineEditing, SelectEditing, ValueEditing
from objectstate import ObjectState
from python_introspect import resolve_annotated
from ui_theme.catalog import SCHEMES


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
        return [cls.showing(type(parameter).__mro__)(field)
                for path, parameter in ParameterFormService().parameters_for_state(state, parent)
                if cls.admits(field := cls.field_type(state, path))]

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


class GroupFields(FieldViews):
    """A nested dataclass: a heading and the views of its fields."""

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
    def pages(cls, state: ObjectState) -> dict[FormPage, FieldForm]:
        """One form per page the top-level fields declare, in declaration order."""
        parts = {part.field.path: part for part in cls.field_family.of(state)}
        return {page: cls(state, [parts[path] for path in paths])
                for page, paths in form_pages(state, parts).items()}

    def filter(self, term: str) -> None:
        self.filter_parts(term)
