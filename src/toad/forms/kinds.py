"""Field kinds a type alone does not say, declared as `Annotated` metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Multiline:
    """Text of several lines: `Annotated[str, Multiline()]`."""
