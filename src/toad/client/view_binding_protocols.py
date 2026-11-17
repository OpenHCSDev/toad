"""Toolkit-neutral protocols for the surface `BoundView` reaches on its host view.

`BoundView` (transcript_publication.py) was written against Textual's `Conversation`
widget, which inherits from `DOMNode` — so it had direct access to `.window`,
`.contents.query_children(...)`, `.query_ancestor(...)`, and `.ancestors`. Qt's
`QtAcpSessionView` can't satisfy those by inheritance; a Qt host instead
implements these protocols to pass the same shape to `BoundView`.

Each protocol declares one accessor. `BoundView` consumes the composed surface
via `BoundViewHost`, which aggregates them so a single type hint reads cleanly at
the call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Protocol, Sequence, TypeVar, runtime_checkable


if TYPE_CHECKING:
    from toad.client.transcript_history_contract import TranscriptHistoryContract
    from toad.session_scope import SessionScope


T = TypeVar("T")


@runtime_checkable
class WindowOwner(Protocol):
    """A host that owns a transcript `window` (`Window` in Textual's conversation; the Qt
    equivalent is responsible for exposing the same reader-position/scroll-revision surface)."""

    @property
    def window(self) -> object: ...


@runtime_checkable
class ChildrenOwner(Protocol):
    """A container that can be queried for its typed children — the shape Textual's
    `Widget.query_children(kind)` exposes and that Qt must mimic (its parent-of-parent
    `findChildren(kind)` returns the same conceptual result)."""

    def query_children(self, kind: type[T]) -> Sequence[T]: ...


@runtime_checkable
class SessionScopeLookup(Protocol):
    """A host that can locate the enclosing `SessionScope` ancestor in its widget tree —
    Textual's `DOMNode.query_ancestor(SessionScope)` and the Qt equivalent."""

    def query_ancestor(self, kind: type["SessionScope"]) -> "SessionScope": ...


@runtime_checkable
class AncestorLineage(Protocol):
    """A host that exposes its ancestor chain as an iterable — Textual's `DOMNode.ancestors`
    and the Qt equivalent walking the parent chain. Membership tests on a specific scope
    (e.g. `source in view.ancestors`) check whether the scope still contains the view."""

    @property
    def ancestors(self) -> Iterable[object]: ...


@runtime_checkable
class BoundViewHost(WindowOwner, SessionScopeLookup, AncestorLineage, Protocol):
    """The composed surface `BoundView.__init__` requires on its host view: a window, a
    SessionScope lookup, an ancestor lineage, a `contents` container, and the view's
    `transcript_history` — the single transcript-page-producing child BoundView drives.
    Textual's `Conversation` satisfies this structurally through its widget tree;
    Qt's view implements the accessors explicitly on the ACP tab's conversation host."""

    @property
    def contents(self) -> ChildrenOwner: ...

    @property
    def transcript_history(self) -> "TranscriptHistoryContract": ...
