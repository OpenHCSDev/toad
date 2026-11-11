"""Posting order belongs to the transcript, including notes without a saved row."""

from __future__ import annotations

from abc import ABC, abstractmethod
from agent_comms.execution.transcript_sources import TranscriptCursor
from textual.widget import Widget


class EntryPlacement(ABC):
    """The source owner supplies entry order and anchors local arrivals."""

    @property
    @abstractmethod
    def live_order(self) -> int: ...

    @property
    @abstractmethod
    def latest_cursor(self) -> TranscriptCursor: ...

    @abstractmethod
    async def keep_before_later_history(self, entry: ChronologicalEntry, cursor: TranscriptCursor) -> None: ...


class PostedEntry:
    """Every posted block takes the order of the source it follows."""

    conversation_order: int = 1

    def prepare_post(self, placement: EntryPlacement) -> None:
        self.conversation_order = placement.live_order

    async def posted(self, placement: EntryPlacement) -> None:
        """Ordinary live output is replaced by its saved source."""


class ChronologicalEntry(PostedEntry, Widget):
    """A local entry stays between the saved prefix and subsequent messages."""

    def prepare_post(self, placement: EntryPlacement) -> None:
        super().prepare_post(placement)
        self.position = placement.latest_cursor

    async def posted(self, placement: EntryPlacement) -> None:
        await placement.keep_before_later_history(self, self.position)
