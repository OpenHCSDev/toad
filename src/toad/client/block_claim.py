from __future__ import annotations

from typing import TYPE_CHECKING

from metaclass_registry.mro_dispatch import handles
from toad.commit_claims import (
    CommitBarrierClaim,
    CommitClaim,
    CommitParticipant,
    RetainedBlockClaim,
)
from toad.core.projection import MroProjection

if TYPE_CHECKING:
    from textual.widget import Widget


class CommitBarrier:
    """A local interactive session whose ordering cannot be replaced by a snapshot."""


class BlockClaims(MroProjection[CommitClaim]):
    """Every block a conversation's contents hold has one commit claim; this is where it is read."""

    # object, not Widget: a history's MRO reaches Widget before its CommitParticipant base.
    @handles(object)
    def retained(self, widget: Widget) -> CommitClaim:
        return RetainedBlockClaim()

    @handles(CommitParticipant)
    def participant(self, widget: CommitParticipant) -> CommitClaim:
        return widget.commit_claim

    @handles(CommitBarrier)
    def barrier(self, widget: CommitBarrier) -> CommitClaim:
        return CommitBarrierClaim()


BLOCK_CLAIMS = BlockClaims()


def block_claim(widget: object) -> CommitClaim:
    return BLOCK_CLAIMS.project_value(widget)
