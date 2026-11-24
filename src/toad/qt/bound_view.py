"""Qt's half of the shared `BoundViewHost` contract: the tree members, walked through Qt.

`BoundViewHost` (toad.client.view_binding_protocols) declares what `BoundView` needs of a
conversation view. Textual's DOM supplies the tree members; a Qt widget supplies them here
from `QWidget.parent()`. The view-specific members (`window`, `contents`,
`transcript_history`) stay abstract and are answered by each Qt view.
"""

from __future__ import annotations

from typing import Iterator

from toad.client.session_scope import SessionScope
from toad.client.view_binding_protocols import BoundViewHost

class QtBoundViewHost(BoundViewHost):
    """The shared host contract's tree members on a Qt widget, walking `QWidget.parent()`
    where Textual walks its DOM. Mixed into QWidget subclasses only."""

    def query_ancestor(self, kind: type[SessionScope]) -> SessionScope:
        for ancestor in self.ancestors:
            if isinstance(ancestor, kind):
                return ancestor
        raise LookupError(f"No ancestor of type {kind.__name__} in the Qt parent chain")

    @property
    def ancestors(self) -> Iterator[object]:
        node = self.parent()
        while node is not None:
            yield node
            node = node.parent()
