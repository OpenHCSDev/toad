"""A context explorer's reads: a capability of anything that holds a Core."""

from __future__ import annotations

from pydantic import JsonValue

from agent_comms.context_store import (
    LATEST_CONTEXT, CapturedContext, ContextManifestCursor, ContextManifestReference,
)
from agent_comms.core_access import CoreAccess
from agent_comms.runtime_server import RuntimeRequest
from agent_comms.thread_identity import ThreadIncarnation
from agent_comms.threads import Thread
from agent_comms.tools import (
    CommsContextInspectionTool, CommsImportedSourceTool, CommsOwnerRequestTool, CommsSavedSegmentTool,
    CommsSavedSourceTool, ContextInspectionRead,
)
from agent_comms.turn_context import ContextSourceText, Provenance, SegmentManifest


class ContextReads:
    """Context reads through this holder's Core, locally or across the connector alike."""

    core: CoreAccess

    def context_inspection(
        self, owner: str, *, cursor: ContextManifestCursor = LATEST_CONTEXT,
        previous: tuple[CapturedContext, ...] = (),
    ) -> ContextInspectionRead:
        return self.core.call(CommsContextInspectionTool(owner=owner, cursor=cursor, previous=previous))

    def owner_request(self, owner: ThreadIncarnation, request: RuntimeRequest) -> JsonValue:
        return self.core.call(CommsOwnerRequestTool(owner=owner, request=request)).payload

    def imported_source(self, owner: Thread, source: Provenance) -> ContextSourceText:
        return self.core.call(CommsImportedSourceTool(owner=owner, source=source))

    def saved_source(self, owner: str, reference: ContextManifestReference, position: int,
                     source: Provenance) -> ContextSourceText:
        return self.core.call(CommsSavedSourceTool(
            owner=owner, reference=reference, position=position, source=source))

    def saved_segment(self, owner: str, reference: ContextManifestReference, position: int,
                      contributors: tuple[int, ...] = ()) -> SegmentManifest:
        return self.core.call(CommsSavedSegmentTool(
            owner=owner, reference=reference, position=position, contributors=contributors))
