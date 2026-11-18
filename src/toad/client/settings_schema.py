"""Toolkit-neutral view of SavedSettings: pages, rows, and a polymorphic row-kind family.

Both Textual and Qt read the same `SavedSettings` state, so parity is already
through that shared store. What was missing was a shared *view* of it: pages
grouped from `FormPage` metadata, leaf rows flattened out of nested groups, and
each leaf's edit surface dispatched by what it declares, not by what each
frontend happens to render.

A frontend asks for `SettingsSchema(saved).pages()`, iterates `SettingsRowSchema`
instances, and renders each row through its own `SettingsRowKind`-dispatched
widget family. Writes go back through `SettingsRowSchema.write()`, which calls
`SavedSettings.set` (with validation) or `.toggle`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import ClassVar, Self

from agent_comms.nominal.declared_choice import DeclaredChoice
from formbridge.forms.declared_fields import DeclaredField, FormPage
from formbridge.forms.parameter_form_service import ParameterFormService
from objectstate import DottedFieldPath
from python_introspect import AnnotationChoices, resolve_annotated

from toad.preferences import SETTINGS, SavedSettings
from toad.setting_choices import SchemeName
from toad.setting_declarations import FamilyChoices


class SettingsRowKind:
    """A capability mixin for a polymorphic row-kind family.

    Each kind declares what annotation types it handles via `shows=(...)`.
    `SettingsRowKind.for_annotation(annotation)` picks the first kind that
    claims one of the annotation's declarations.
    """

    shows: ClassVar[tuple[object, ...]] = ()

    def __init_subclass__(cls, *, shows: tuple[object, ...] = (), **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.shows = shows

    @classmethod
    def members(cls) -> Iterator[type[Self]]:
        yield cls
        for member in cls.__subclasses__():
            yield from member.members()

    @classmethod
    def for_field(cls, field: DeclaredField) -> SettingsRowKind:
        """Pick the right kind for this field's annotation and bind it to the field."""
        # FamilyChoices and SchemeName are metadata on the annotation, checked first.
        family = field.metadata(FamilyChoices)
        if family is not None:
            return ChoicesRowKind(
                options=tuple(
                    (choice.choice_label(), choice) for choice in family.choices()
                )
            )
        scheme = field.metadata(SchemeName)
        if scheme is not None:
            return SchemeChoiceRowKind()
        resolved = resolve_annotated(field.annotation)
        if resolved is bool:
            return BoolRowKind()
        if resolved is int:
            return IntRowKind()
        if resolved is float:
            return FloatRowKind()
        if resolved is str:
            return StrRowKind()
        # Fallback: treat as a string for display; write path still validates.
        return StrRowKind()


class BoolRowKind(SettingsRowKind, shows=(bool,)):
    """A yes/no setting, toggled by a check box."""


@dataclass(frozen=True)
class IntRowKind(SettingsRowKind, shows=(int,)):
    """A whole number, bounded by the field's annotated interval when declared."""


@dataclass(frozen=True)
class FloatRowKind(SettingsRowKind, shows=(float,)):
    """A real number, bounded by the field's annotated interval when declared."""


class StrRowKind(SettingsRowKind, shows=(str,)):
    """A short string of free text."""


@dataclass(frozen=True)
class ChoicesRowKind(SettingsRowKind, shows=(FamilyChoices,)):
    """One of a named list of choices (declared family members)."""

    options: tuple[tuple[str, object], ...]


class SchemeChoiceRowKind(SettingsRowKind, shows=(SchemeName,)):
    """The name of one of the running app's colour schemes (choices supplied at render)."""


@dataclass(frozen=True)
class SettingsRowSchema:
    """One editable setting, viewed toolkit-neutrally."""

    field: DeclaredField
    kind: SettingsRowKind
    saved: SavedSettings

    @property
    def label(self) -> str:
        return self.field.label

    @property
    def help(self) -> str:
        return self.field.help

    @property
    def path(self) -> DottedFieldPath:
        return self.field.path

    @property
    def value(self) -> object:
        return self.field.value

    @property
    def search_text(self) -> str:
        return self.field.search_text

    @property
    def bounds_text(self) -> str:
        return self.field.bounds_text

    def write(self, value: object) -> None:
        """Send one edit through SavedSettings (validates + publishes events)."""
        from objectstate import DottedFieldPath as _P  # type: ignore[import-not-found]
        # SavedSettings.set takes a FieldPath (built via SETTINGS.*); translate dotted path.
        self.saved.set(self._field_path(), value)

    def toggle(self) -> None:
        self.saved.toggle(self._field_path())

    def _field_path(self):
        """Rebuild a FieldPath from the dotted path by walking SETTINGS attribute-by-attribute."""
        path = SETTINGS
        for step in self.path.value.split("."):
            path = getattr(path, step)
        return path


@dataclass(frozen=True)
class SettingsPageSchema:
    """One tab's worth of rows."""

    page: FormPage
    rows: tuple[SettingsRowSchema, ...]

    @property
    def title(self) -> str:
        return self.page.title


def leaf_fields[Field: DeclaredField](root: Field) -> Iterator[Field]:
    """Every leaf field below ``root`` (``root`` itself when it is one), of ``root``'s own
    field type, so a view's fields stay the view's."""
    state = root.state
    if state.has_parameter_descendants(root.path.value):
        for path, _parameter in ParameterFormService().parameters_for_state(state, root.path.value):
            yield from leaf_fields(type(root)(state, path))
        return
    yield root


@dataclass(frozen=True)
class ObjectSettingRow(SettingsRowSchema):
    """One setting of a viewed object: an edit goes through the view's configuration
    (`ObjectSettingField.edit`: the view's override, or the app default where the view may
    not override it), as Textual's object form writes it."""

    @classmethod
    def rows(cls, field: DeclaredField, saved: SavedSettings) -> tuple[ObjectSettingRow, ...]:
        return tuple(cls(field=leaf, kind=SettingsRowKind.for_field(leaf), saved=saved)
                     for leaf in leaf_fields(field))

    def write(self, value: object) -> None:
        self.field.edit(value)

    def toggle(self) -> None:
        self.field.edit(not self.field.value)


class SettingsSchema:
    """The pages and rows of the running app's SavedSettings, read as plain data."""

    def __init__(self, saved: SavedSettings) -> None:
        self.saved = saved

    def pages(self) -> tuple[SettingsPageSchema, ...]:
        """One page per declared `FormPage`, in declaration order."""
        state = self.saved.state
        grouped: dict[FormPage, list[SettingsRowSchema]] = {}
        order: list[FormPage] = []
        for path, _parameter in ParameterFormService().parameters_for_state(state, ""):
            top = DeclaredField(state, path)
            page = top.metadata(FormPage) or FormPage("")
            if page not in grouped:
                grouped[page] = []
                order.append(page)
            grouped[page].extend(self._leaves(top))
        return tuple(
            SettingsPageSchema(page=page, rows=tuple(grouped[page])) for page in order
        )

    def _leaves(self, root: DeclaredField) -> Iterator[SettingsRowSchema]:
        """Every leaf below `root` (including `root` itself if it is a leaf)."""
        for leaf in leaf_fields(root):
            yield SettingsRowSchema(field=leaf, kind=SettingsRowKind.for_field(leaf), saved=self.saved)

    def discard(self) -> None:
        self.saved.discard()

    def finish(self) -> None:
        """Flush any buffered edits held by other open settings views."""
        for callback in list(self.saved.open_edits):
            callback()
