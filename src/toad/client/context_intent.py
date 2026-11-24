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

from toad.client.panel_source import PanelSource
from toad.core.context_inspection import (
    ContextNode,
    DetachedInspection,
    InspectionState,
)
from toad.thread_identity import SessionIdentity

if TYPE_CHECKING:
    from textual.worker import Worker



@dataclass
class ContextTreeIntent:
    """Detail selection and initial disclosures survive widget retirement.

    The mounted Tree owns navigation; selected is the detail source, not its cursor.
    """

    expanded: set[str] = field(default_factory=set)
    selected: ContextNode | None = None
    query: str = ""
    cursor: ContextManifestCursor = LATEST_CONTEXT

    def select_page(self, cursor: ContextManifestCursor) -> None:
        self.cursor = cursor
        self.selected = None

    def search_current(self, query: str, selected) -> bool:
        return self.query == query and self.selected is selected

    def rebind(self, original: ContextNode, model: ContextNode) -> None:
        if self.selected is original:
            self.selected = model

    def restore_detail(
        self,
        resolve,
        show_detail: Callable[[ContextNode], Worker[None]],
    ) -> bool:
        if self.selected is None:
            return False
        node = resolve(self.selected.key)
        if node is None:
            return False
        self.selected = node.data
        show_detail(self.selected)
        return True


class ContextInspectionReader(PanelSource):
    """The context explorer's reading state, as both frontends hold it: Textual's
    `ContextExplorer` and Qt's `QtContextExplorer` inherit this. It keeps the per-thread
    intents store, the current `InspectionState`, and each step a read moves that state
    through; the frontend owns only when it reads and how it draws."""

    def start_inspection(self, intents: dict[SessionIdentity, ContextTreeIntent]) -> None:
        """Each frontend's constructor calls this once beside its widget's own."""
        self._intents = intents
        self.state: InspectionState = DetachedInspection()

    @property
    def intent(self) -> ContextTreeIntent:
        """The viewed thread's intent, kept across widget retirements."""
        return self._intents.setdefault(self.thread_identity, ContextTreeIntent())

    def inspect_identity(self, identity: SessionIdentity) -> None:
        """A new thread starts its own inspection."""
        self.state = identity.inspection_state()

    def observe_revision(self, revision) -> InspectionState:
        """Mark the coordination revision this read observes; returns the state before it."""
        previous = self.state
        self.state = previous.observe(revision)
        return previous

    async def acquire_inspection(self, observed, revision, identity):
        """Read the inspection at the intent's page cursor."""
        return await self.state.acquire(observed, revision, identity, cursor=self.intent.cursor)

    def receive_inspection(self, acquired) -> None:
        self.state = self.state.receive_inspection(acquired)
