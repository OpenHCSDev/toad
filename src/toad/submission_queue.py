"""The source owns what its input queue shows and how it sends queued work now."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agent_comms.acp_extension import QueueItem

from toad.agent_presentation import AgentPresentation

if TYPE_CHECKING:
    from toad.acp.agent import Agent


@dataclass(frozen=True)
class QueueEvidence:
    """One UI read of the queue: the agent's presentation and this view's outstanding requests."""

    presentation: AgentPresentation
    delivering: tuple[str, ...]


class QueueSource(ABC):
    preview_limit: ClassVar[int] = 3

    @abstractmethod
    def queue_summary(self, evidence: QueueEvidence) -> str: ...


class NativeQueueSource(QueueSource):
    def queue_summary(self, evidence: QueueEvidence) -> str:
        presentation = evidence.presentation
        projection = presentation.queue
        feedback = projection.feedback(presentation.queue_supported)
        parts = [feedback] if feedback else []
        for label, texts, detail in (
            ("Submitting", tuple(QueueItem.summarize(text) for text in evidence.delivering), ""),
            ("Queued", tuple(row.preview for row in projection.items), ""),
            ("Restored", tuple(row.preview for row in projection.restored), ", read-only"),
        ):
            if texts:
                parts.append(f"{label} ({len(texts)}{detail}): " + " · ".join(texts[:self.preview_limit]))
        return " | ".join(parts)
