"""A field of a dataclass tree, named through the declarations instead of a string."""

from __future__ import annotations

from dataclasses import Field, fields, is_dataclass
from python_introspect import UnifiedParameterAnalyzer, resolve_annotated, resolve_optional


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


def declared_field(path: FieldPath) -> Field[object]:
    """The dataclass field the path names, with the metadata it was declared with."""
    name = path._names[-1]
    return next(field for field in fields(declared_type(parent(path))) if field.name == name)


def steps(path: FieldPath) -> tuple[FieldPath, ...]:
    """The fields passed on the way down to this one, itself last."""
    return tuple(
        FieldPath(path._root, path._names[:count]) for count in range(1, len(path._names) + 1)
    )


def fields_below(path: FieldPath) -> tuple[FieldPath, ...]:
    """The fields of the dataclass this path holds; none when it holds a plain value."""
    owner = declared_type(path)
    if not is_dataclass(owner):
        return ()
    return tuple(getattr(path, field.name) for field in fields(owner))


def leaves(path: FieldPath) -> tuple[FieldPath, ...]:
    """Every plain-valued field at or below this path."""
    below = fields_below(path)
    if not below:
        return (path,)
    return tuple(leaf for child in below for leaf in leaves(child))
