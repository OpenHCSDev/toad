"""Saved transcript availability and bus-input proof have separate owners."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation
    from toad.widgets.native_history import NativeHistory


class SessionHistoryDetails:
    def __init__(self, transcript: TranscriptPresentation | None, native: NativeHistory | None):
        self.transcript = transcript
        self.native = native

    @property
    def summary(self):
        parts = []
        if self.transcript is not None:
            parts.append("Saved history available" if self.transcript.reports_coverage
                         else "Saved history not loaded")
        if self.attention:
            parts.append("Bus input verification unavailable")
        return parts

    @property
    def attention(self):
        return self.native is not None and self.native.status == "unavailable"

    def overview(self, activity):
        return "\n\n".join([
            *self.summary,
            *(str(item.render()) for item in (activity, self.native)
              if item is not None and item.display),
        ])
