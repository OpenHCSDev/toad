"""Widget families whose members say which declarations they show."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from inspect import cleandoc
from typing import Annotated, ClassVar, Optional, Self, TypeVar, get_args, get_origin

from formbridge.forms.ui_utils import FieldDisplayText
from objectstate import ObjectState
from python_introspect import (
    ParameterInfo,
    declared_field_label,
    optional_member_type,
    resolve_annotated,
    resolve_optional,
)
from python_introspect.validation import validate_annotation_value

from toad.forms.field_path import FieldPath
from toad.forms.kinds import Placeholder

Metadata = TypeVar("Metadata")


class DeclaredViews:
    """A family of widget classes, each registered under what it shows.

    A class directly below this one starts a family. A member names the
    declarations it shows in its own body (`shows = (int,)`), so adding a kind
    of field is adding a class: nothing lists the members and nothing chooses
    between them by testing types.

    Textual follows the first DOM base for native focus and CSS. A pure editor
    capability may precede that base so its cooperative initializer binds the
    field before the native control consumes it.
    """

    shows: ClassVar[tuple[object, ...]] = ()
    shown_by: ClassVar[dict[object, type]]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if DeclaredViews in cls.__bases__:
            cls.shown_by = {}
        for declaration in vars(cls).get("shows", ()):
            cls.shown_by[declaration] = cls

    @classmethod
    def showing(cls, declarations: Iterable[object]) -> type[Self]:
        """The member registered under the first of these declarations that has one."""
        declarations = tuple(declarations)
        for declaration in declarations:
            if declaration in cls.shown_by:
                return cls.shown_by[declaration]
        raise LookupError(f"No {cls.__name__} shows any of {declarations!r}")


def declarations(annotation: object) -> Iterator[object]:
    """What an annotation declares, most specific first.

    `Annotated` metadata comes before the type it annotates, `T | None` is
    `Optional`, and a class is followed by its bases.
    """
    if get_origin(annotation) is Annotated:
        base, *metadata = get_args(annotation)
        for item in metadata:
            yield from type(item).__mro__[:-1]
        yield from declarations(base)
    elif optional_member_type(annotation) is not None:
        yield Optional
    else:
        declared = get_origin(annotation) or annotation
        yield from declared.__mro__[:-1] if isinstance(declared, type) else (declared,)


@dataclass(frozen=True)
class DeclaredField:
    """One field of an ObjectState: where its value lives and how it was declared."""

    state: ObjectState
    path: FieldPath

    @property
    def declaration(self) -> ParameterInfo:
        return self.state.parameter_structure.declarations[str(self.path)]

    @property
    def annotation(self) -> object:
        return self.declaration.param_type

    def metadata(self, kind: type[Metadata]) -> Metadata | None:
        """Metadata of the admitted field, including an optional member's metadata."""
        for annotation in (self.annotation, resolve_optional(resolve_annotated(self.annotation))):
            if get_origin(annotation) is Annotated:
                for item in get_args(annotation)[1:]:
                    if isinstance(item, kind):
                        return item
        return None

    @property
    def value(self) -> object:
        return self.state.get_resolved_value(str(self.path))

    @property
    def default(self) -> object:
        return self.declaration.default_value

    @property
    def has_default(self) -> bool:
        return not self.declaration.is_required

    @property
    def placeholder(self) -> str:
        hint = self.metadata(Placeholder)
        return hint.text if hint is not None else ""

    @property
    def label(self) -> str:
        return (
            declared_field_label(self.annotation)
            or FieldDisplayText.from_field_name(self.declaration.name).display_name
        )

    @property
    def help(self) -> str:
        return cleandoc(self.declaration.description or "")

    @property
    def member(self) -> DeclaredField:
        """The same field as declared without `None`."""
        return OptionalMemberField(self.state, self.path)

    def edit(self, value: object) -> None:
        """Give the field a value, unless its declaration does not accept it.

        Raises:
            TypeError, ValueError: the value is not one the annotation allows.
        """
        # ObjectState takes any value for a field of the root object and only
        # fails later, when the object is rebuilt (ObjectState issue #47).
        validate_annotation_value(self.annotation, value, path=self.label)
        self.state.update_parameter(str(self.path), value)


class OptionalMemberField(DeclaredField):
    """The member editor reads a narrower annotation, not a copied declaration."""

    @property
    def annotation(self) -> object:
        return optional_member_type(super().annotation)
