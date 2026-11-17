"""Qt-side host that satisfies `BoundViewHost` so a plain `BoundView` can drive the
Qt ACP transcript pipeline the same way it drives Textual's.

`BoundView` (`src/toad/transcript_publication.py`) consumes `BoundViewHost` (four
protocols composed in `src/toad/client/view_binding_protocols.py`): `window`,
`contents` (a `ChildrenOwner`), `query_ancestor`, `ancestors`. Textual's
`Conversation` satisfies those by inheriting `DOMNode`. Qt widgets have no DOMNode
— they expose an analogous shape through `QWidget.parent()`, `QWidget.window()`
and `QWidget.findChildren()`. This module names the mixin Qt views add so that
protocol inherits cleanly instead of being duplicated per widget.
"""

from __future__ import annotations

from typing import Iterator, Sequence, TYPE_CHECKING, TypeVar

from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from toad.session_scope import SessionScope


T = TypeVar("T")


class QtChildrenOwner:
    """Backing for `BoundViewHost.contents`: exposes a Qt widget's descendants of a
    given type under the shared `query_children(kind)` name. Qt's `findChildren`
    already recurses the parent–child tree, so the same shape Textual gets from
    `Widget.query_children` is one method call here."""

    def query_children(self, kind: type[T]) -> Sequence[T]:
        if not isinstance(self, QWidget):
            raise TypeError(
                f"QtChildrenOwner expected a QWidget host, got {type(self).__name__}; "
                "mix it in only on Qt widgets."
            )
        return self.findChildren(kind)


class QtBoundViewHost(QtChildrenOwner):
    """Mixin satisfying `BoundViewHost` for a Qt widget that stands in for Textual's
    `Conversation` on the ACP tab. Subclasses must expose `.window` (a Window-shaped
    object tracking `scroll_revision`) and `.contents` (another `QtChildrenOwner`
    Qt widget that owns the `TranscriptHistory` descendants) — both are view-specific
    plumbing that can't be inferred from Qt's own parent chain.

    The lookups below walk `QWidget.parent()` instead of Textual's DOM traversal.
    `query_ancestor(kind)` returns the first ancestor whose class matches `kind`,
    raising `LookupError` to match the Textual API's exception shape. `ancestors`
    is a generator of every parent up to the top-level window.
    """

    def query_ancestor(self, kind: type["SessionScope"]) -> "SessionScope":
        for ancestor in self.ancestors:
            if isinstance(ancestor, kind):
                return ancestor  # type: ignore[return-value]
        raise LookupError(f"No ancestor of type {kind.__name__} in the Qt parent chain")

    @property
    def ancestors(self) -> Iterator[object]:
        node = self.parent() if isinstance(self, QWidget) else None
        while node is not None:
            yield node
            node = node.parent() if isinstance(node, QWidget) else None
