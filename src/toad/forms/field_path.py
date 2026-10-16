"""A field of a dataclass tree, named through the declarations instead of a string."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from objectstate import ObjectState

from python_introspect import UnifiedParameterAnalyzer, resolve_annotated, resolve_optional

from toad.forms.declared_views import DeclaredField


class FieldPath:
    """One field of a dataclass tree: `FieldPath(Settings).sidebar.hide`.

    Each step is checked against the dataclass fields when the path is built,
    so a path that exists names a declared field. `str(path)` is the dotted
    name ObjectState keeps the field under.
    """

    __slots__ = ("_root", "_names")

    def __init__(self, root: type, names: tuple[str, ...] = ()) -> None:
        self._root, self._names = root, names

    def __getattr__(self, name: str) -> FieldPath:
        owner = declared_type(self)
        if not is_dataclass(owner) or name not in {field.name for field in fields(owner)}:
            raise AttributeError(f"{owner!r} declares no field {name!r}")
        return FieldPath(self._root, (*self._names, name))

    def __str__(self) -> str:
        return ".".join(self._names)

    def __repr__(self) -> str:
        return f"FieldPath({self._root.__name__}, {str(self)!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FieldPath)
            and (self._root, self._names) == (other._root, other._names)
        )

    def __hash__(self) -> int:
        return hash((self._root, self._names))

    def bind(self, state: ObjectState) -> DeclaredField:
        """Bind this declaration to the field ObjectState declares at this path."""
        if not issubclass(state.type_for_path(""), self._root):
            raise TypeError(f"{self!r} does not name a field of this ObjectState")
        return DeclaredField(state, state.parameter_structure.path(str(self)))

    def matches(self, field: DeclaredField) -> bool:
        """Whether this declaration names the bound field, including its root type."""
        return (
            issubclass(field.state.type_for_path(""), self._root)
            and field.path.parts == self._names
        )


def parent(path: FieldPath) -> FieldPath:
    return FieldPath(path._root, path._names[:-1])


def declared_annotation(path: FieldPath) -> object:
    """The field's annotation as written, `Annotated` metadata included."""
    if not path._names:
        return path._root
    return UnifiedParameterAnalyzer.analyze(declared_type(parent(path)))[
        path._names[-1]
    ].param_type


def declared_type(path: FieldPath) -> object:
    """The type a value of the field has, without `Annotated` and `Optional`."""
    return resolve_annotated(resolve_optional(resolve_annotated(declared_annotation(path))))
