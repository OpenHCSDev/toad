"""Captured thread reads; settlement belongs to their original attachment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.thread_presentation import ThreadPresentation

if TYPE_CHECKING:
    from toad.acp.agent import Agent
    from toad.acp.client_session import ClientSessionRequest
    from toad.acp.comms_updates import OwnerSnapshotConsumer
    from toad.acp.coordination_attachment import CoordinatedThread


class ThreadReadOutcome:
    """A status read may publish only while its captured source still holds."""

    def present(self, consumer) -> None:
        """Expired observations leave the newer session's presentation alone."""


class EndedSessionRead(ThreadReadOutcome):
    """The read's client session ended before its result arrived."""


class ChangedAttachmentRead(ThreadReadOutcome):
    """The read's original thread is no longer attached to this client."""


@dataclass(frozen=True)
class SettledThreadRead(ThreadReadOutcome):
    presentation: ThreadPresentation

    def present(self, consumer) -> None:
        consumer(self.presentation)


class ThreadRead:
    """A presentation read, with settlement owned by its captured source."""

    def settle(self, presentation: ThreadPresentation) -> ThreadReadOutcome:
        return SettledThreadRead(presentation)

    async def reconcile(self, transcripts) -> None:
        """An uncaptured read has no owner snapshot to reconcile."""


class NoPendingThreadRead(ThreadRead):
    """No captured client authority; present the current observation directly."""


@dataclass(frozen=True)
class PendingThreadRead(ThreadRead):
    """Retain attachment, request and turn identities from before the read."""

    agent: Agent
    coordination: CoordinatedThread
    authority: ClientSessionRequest
    snapshot: OwnerSnapshotConsumer

    def settle(self, presentation: ThreadPresentation) -> ThreadReadOutcome:
        if not self.agent.coordination_attachment.matches_source(self.coordination.update):
            return ChangedAttachmentRead()
        if self.authority.retired:
            return EndedSessionRead()
        self.snapshot.dispatch_sync(presentation)
        return SettledThreadRead(presentation)

    async def reconcile(self, transcripts) -> None:
        read = await transcripts.thread_presentation(
            self.coordination.update.wire_root, self.coordination.update.thread.name
        )
        self.settle(read.raised())
