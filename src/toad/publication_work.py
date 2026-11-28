from __future__ import annotations

from agent_comms.coordination.errors import TranscriptChanged
from textual.worker import Worker


class PublicationWork:
    """No publication is running: nothing to cancel or join, and a commit has nothing to settle."""

    @property
    def is_finished(self) -> bool:
        return True

    def runs(self, worker: Worker) -> bool:
        return False

    def cancel(self) -> None:
        pass

    async def joined(self) -> None:
        """Cancel this work and wait until it has stopped."""

    async def settled(self) -> None:
        """Wait for the commit this work publishes; with none running, the transcript moved on."""
        raise TranscriptChanged()
