"""Toolkit-neutral ancestor walk for widget trees.

Replaces Textual's `query_ancestor(T)` and Qt's manual `parent()` chain with one
helper driven by an `AncestorChain` Protocol. Textual's `DOMNode` and Qt's
`QWidget` both expose a parent attribute; each backend implements `AncestorChain`
once and every consumer uses `find_ancestor(widget, T)` instead of toolkit-specific
traversal.
"""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable


T = TypeVar("T")


@runtime_checkable
class AncestorChain(Protocol):
    """A widget that can walk to its parent widget."""

    def parent_widget(self) -> "AncestorChain | None":
        """The widget containing this one, or None at the root."""


def find_ancestor(widget: AncestorChain, kind: type[T]) -> T:
    """Walk `widget.parent_widget()` until an instance of `kind` is found.

    Raises LookupError if the tree ends before an ancestor of `kind` is reached.
    Call sites that expect the ancestor to exist (every current call does — the
    scopes are declared on the root application) should not guard this.
    """
    current: AncestorChain | None = widget
    while current is not None:
        if isinstance(current, kind):
            return current
        current = current.parent_widget()
    raise LookupError(f"No ancestor of type {kind.__name__!r} in the widget chain")
