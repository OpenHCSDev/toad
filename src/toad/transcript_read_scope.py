"""Transcript read capability, independent of submission and rich session views."""
from abc import ABC, abstractmethod

from agent_comms.transcripts import AtFrontier, LatestPage, LivePageSource, PageLimit, PagePosition, PageSource
from agent_comms.ui_model.observation import ReadTranscript, ReadTranscriptUpdate, TranscriptPublicationState


class TranscriptReadScope(ABC):
    @property
    @abstractmethod
    def readable(self) -> bool: ...

    @abstractmethod
    def snapshot_request(
        self, *, position: PagePosition = LatestPage(), limit: PageLimit = AtFrontier(),
        page_source: PageSource = LivePageSource(),
    ) -> ReadTranscript: ...

    @abstractmethod
    def update_request(
        self, previous: TranscriptPublicationState, *, position: PagePosition = LatestPage(),
    ) -> ReadTranscriptUpdate: ...
