"""What a frontend without a draft-rendering row shows for the thread's CLI draft.

Core reports a draft row or none; this answers, once for every frontend, the line of text
that stands for it: the last line of the draft's text events, an ellipsis for a draft with
no text yet, and nothing when no draft stands.
"""

from __future__ import annotations

from agent_comms.execution.transcript_sources import DraftRow
from agent_comms.transcript.transcript_drafts import NoDraft
from metaclass_registry.mro_dispatch import handles

from toad.client.fragments import COPIED_TEXT
from toad.core.projection import MroProjection


class DraftSummary(MroProjection[str | None]):
    @handles(DraftRow)
    def draft(self, draft: DraftRow) -> str | None:
        text = "".join(COPIED_TEXT.project_value(event) for event in draft.events).strip()
        return text.splitlines()[-1] if text else "…"

    @handles(NoDraft)
    def none(self, draft: NoDraft) -> str | None:
        return None


DRAFT_SUMMARY = DraftSummary()
