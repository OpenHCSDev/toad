"""Saved transcript availability and bus-input proof have separate owners."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.transcript_publication import TranscriptPresentation
    from toad.widgets.native_history import NativeHistory


class SessionHistoryDetails:
    def __init__(self, transcript: TranscriptPresentation | None, native: NativeHistory):
        self.transcript = transcript
        self.native = native

    @property
    def summary(self):
        parts = []
        if self.transcript is not None:
            parts.append("Saved history available" if self.transcript.reports_coverage
                         else "Saved history not loaded")
        status = self.native.status
        if status.summary:
            parts.append(status.summary)
        return parts

    def overview(self, activity_lines: tuple[str, ...]):
        return "\n\n".join([
            *self.summary,
            *activity_lines,
            *(str(item.render()) for item in (self.native,)
              if item.display),
        ])
