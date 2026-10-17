"""Field kinds a type alone does not say, declared as `Annotated` metadata."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Placeholder:
    """Text for an empty field, not an offered or persisted value."""

    text: str


@dataclass(frozen=True)
class Multiline:
    """Text of several lines: `Annotated[str, Multiline()]`."""
