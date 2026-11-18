"""The fragments that stand for a thread's CLI draft, for a frontend that draws them as rows.

Core reports a draft row or none. A draft is drawn with the committed transcript's fragment
family, after the history, as Textual's `CliDraft` draws it; no draft draws nothing.
"""

from __future__ import annotations

from agent_comms.execution.transcript_sources import DraftRow
from agent_comms.transcript.transcript_drafts import NoDraft
from metaclass_registry.mro_dispatch import handles

from toad.client.transcript_fragments import FragmentClasses, FragmentPlan, TranscriptFragment
from toad.core.projection import MroProjection


class DraftFragments(MroProjection[tuple[TranscriptFragment, ...]]):
    @handles(DraftRow)
    def draft(self, draft: DraftRow, identity, classes: FragmentClasses) -> tuple[TranscriptFragment, ...]:
        return FragmentPlan.for_draft(draft, identity, classes).fragments()

    @handles(NoDraft)
    def none(self, draft: NoDraft, identity, classes: FragmentClasses) -> tuple[TranscriptFragment, ...]:
        return ()


DRAFT_FRAGMENTS = DraftFragments()
