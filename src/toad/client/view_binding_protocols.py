"""The surface `BoundView` reaches on its host view, declared once for every frontend.

`BoundView` (transcript_publication.py) drives a conversation view through five members:
its transcript `window`, the `contents` container holding its transcript blocks, the
`transcript_history` it pages, the enclosing `SessionScope` (`query_ancestor`), and the
view's `ancestors`. Textual's `Conversation` and Qt's thread views both inherit
`BoundViewHost`; Textual's DOM supplies the tree members, Qt's `QtBoundViewHost` walks
`QWidget.parent()`. A host that leaves a member out fails at instantiation.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Iterable


if TYPE_CHECKING:
    from toad.client.transcript_history_contract import TranscriptHistoryContract
    from toad.session_scope import SessionScope


class BoundViewHost:
    """What `BoundView.__init__` requires of its host view. A plain mixin, like the other
    shared view bases: each toolkit's widget metaclass (`AbstractHooksMeta`) refuses a view
    class that leaves one of these abstract."""

    @property
    @abstractmethod
    def window(self) -> object:
        """The transcript window: its reader position and scroll revision."""

    @property
    @abstractmethod
    def contents(self) -> object:
        """The native container holding the view's transcript blocks; `BoundView.current`
        reads its `is_attached`."""

    @property
    @abstractmethod
    def transcript_history(self) -> "TranscriptHistoryContract":
        """The single transcript-page-producing child `BoundView` drives."""

    @abstractmethod
    def query_ancestor(self, kind: type["SessionScope"]) -> "SessionScope":
        """The enclosing `SessionScope`; `LookupError` when the view has none."""

    @property
    @abstractmethod
    def ancestors(self) -> Iterable[object]:
        """Every ancestor up the tree; `source in view.ancestors` asks whether a scope
        still contains the view."""
