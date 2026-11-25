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

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agent_comms.context_store import LATEST_CONTEXT, ContextManifestCursor
from agent_comms.coordination.errors import Refused

from toad.client.panel_source import PanelSource
from toad.core.context_inspection import (
    ContextNode,
    DetachedInspection,
    HoldingInspection,
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

    def still_reading_identity(self, identity: SessionIdentity) -> bool:
        """Whether this panel is still viewing `identity` when an async read finishes."""
        return self.thread_identity == identity

    def set_page_controls(self, *, older: bool, newer: bool) -> None:
        raise NotImplementedError

    def set_status_text(self, text: str) -> None:
        raise NotImplementedError

    def present_inspection(self, holding: HoldingInspection) -> None:
        raise NotImplementedError

    def native_running(self) -> bool:
        raise NotImplementedError

    def cancel_native_read(self) -> None:
        raise NotImplementedError

    def start_native_read(self, captured: HoldingInspection) -> None:
        raise NotImplementedError

    def _inspection_acquired(
        self, previous: InspectionState, current: HoldingInspection, force: bool
    ) -> None:
        self.set_page_controls(
            older=current.inspection.page.has_older(),
            newer=current.inspection.page.has_newer(),
        )
        if previous.inspection_differs(current.inspection) or force:
            current.present_acquired(previous, self.present_inspection)
        if previous.needs_native(current.inspection, force):
            source_changed = not previous.same_source(current.inspection)
            if source_changed and self.native_running():
                self.cancel_native_read()
            if force or source_changed or not self.native_running():
                self.set_status_text(current.status)
                current.prepare_native(self.start_native_read)

    async def _run_native_read(self, captured: HoldingInspection) -> None:
        try:
            native = await captured.inspection.native()
        except asyncio.CancelledError:
            raise
        except Refused as error:
            if self.still_reading_identity(captured.thread_identity):
                self._native_acquired(self.state.native_failed(captured.inspection, error))
        else:
            if self.still_reading_identity(captured.thread_identity):
                self._native_acquired(self.state.with_native(captured.inspection, native))

    def _native_acquired(self, updated: InspectionState) -> None:
        if updated is not self.state:
            self.state = updated
            updated.present(self.present_inspection)
        self.set_status_text(updated.status)
