"""Widget families whose members say which declarations they show."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from inspect import cleandoc
from typing import Annotated, ClassVar, Optional, Self, get_args, get_origin

from objectstate import ObjectState
from python_introspect import optional_member_type
from python_introspect.validation import validate_annotation_value

from toad.forms.field_path import FieldPath, declared_annotation, label


class DeclaredViews:
    """A family of widget classes, each registered under what it shows.

    A class directly below this one starts a family. A member names the
    declarations it shows in its own body (`shows = (int,)`), so adding a kind
    of field is adding a class: nothing lists the members and nothing chooses
    between them by testing types.

    Textual reads a widget's focus and CSS from its first base, so a member
    names its Textual class first and its family after it.
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
    annotation: object

    @classmethod
    def at(cls, state: ObjectState, path: FieldPath) -> DeclaredField:
        return cls(state, path, declared_annotation(path))

    @property
    def value(self) -> object:
        return self.state.get_resolved_value(str(self.path))

    @property
    def default(self) -> object:
        return self.state.signature_default(str(self.path))

    @property
    def label(self) -> str:
        return label(self.path)

    @property
    def help(self) -> str:
        return cleandoc(self.state.parameter_descriptions.get(str(self.path)) or "")

    @property
    def member(self) -> DeclaredField:
        """The same field as declared without `None`."""
        return replace(self, annotation=optional_member_type(self.annotation))

    def edit(self, value: object) -> None:
        """Give the field a value, unless its declaration does not accept it.

        Raises:
            TypeError, ValueError: the value is not one the annotation allows.
        """
        # ObjectState takes any value for a field of the root object and only
        # fails later, when the object is rebuilt (ObjectState issue #47).
        validate_annotation_value(self.annotation, value, path=self.label)
        self.state.update_parameter(str(self.path), value)
