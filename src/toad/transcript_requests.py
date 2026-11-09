"""A transcript address supplies page requests without depending on native views."""

from abc import ABC, abstractmethod

from agent_comms.transcript.transcripts import (
    AtFrontier,
    LatestPage,
    LivePageSource,
    PageLimit,
    PagePosition,
    PageSource,
)
from agent_comms.ui_model.observation import (
    ReadTranscript,
    ReadTranscriptUpdate,
    TranscriptPublicationState,
)


class TranscriptRequests(ABC):
    """The page and currency requests required by a transcript reader."""

    @abstractmethod
    def snapshot_request(
        self,
        *,
        position: PagePosition = LatestPage(),
        limit: PageLimit = AtFrontier(),
        page_source: PageSource = LivePageSource(),
    ) -> ReadTranscript: ...

    @abstractmethod
    def update_request(
        self,
        previous: TranscriptPublicationState,
        *,
        position: PagePosition = LatestPage(),
    ) -> ReadTranscriptUpdate: ...
