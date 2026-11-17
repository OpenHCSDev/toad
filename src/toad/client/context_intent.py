"""Toolkit-neutral context tree intent.

Both the Textual `ContextExplorer` (`widgets/context_explorer.py`) and the Qt
`QtContextExplorer` (`qt/context_panel.py`) reach into the same per-thread intent
store (detail selection, disclosure set, query, page cursor) so the user's
inspection survives a widget retirement on either frontend, and so neither
frontend hand-rolls its own copy of "what context is selected".

`ContextTreeIntent` is the per-thread state. `_intents: dict[SessionIdentity,
ContextTreeIntent]` is the panel-level store that outlives widget instances.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_comms.context_store import LATEST_CONTEXT, ContextManifestCursor

if TYPE_CHECKING:
    from textual.worker import Worker

    from toad.core.context_inspection import ContextNode


@dataclass
class ContextTreeIntent:
    """Detail selection and initial disclosures survive widget retirement.

    The mounted Tree owns navigation; selected is the detail source, not its cursor.
    """

    expanded: set[str] = field(default_factory=set)
    selected: "ContextNode | None" = None
    query: str = ""
    cursor: ContextManifestCursor = LATEST_CONTEXT

    def select_page(self, cursor: ContextManifestCursor) -> None:
        self.cursor = cursor
        self.selected = None

    def search_current(self, query: str, selected) -> bool:
        return self.query == query and self.selected is selected

    def rebind(self, original: "ContextNode", model: "ContextNode") -> None:
        if self.selected is original:
            self.selected = model

    def restore_detail(
        self,
        resolve,
        show_detail: "Callable[[ContextNode], Worker[None]]",
    ) -> bool:
        if self.selected is None:
            return False
        node = resolve(self.selected.key)
        if node is None:
            return False
        self.selected = node.data
        show_detail(self.selected)
        return True
