"""Qt's TranscriptHistory: `QtConversationHistory` specialized for transcript sources.

Mirrors Textual's `TranscriptHistory[ViewT]` at
`src/toad/widgets/transcript_history.py:943` — the same `CommittedHistoryBase` +
`ReportsCoveredPages` bases, the same page type (`PreparedTranscriptPage`), and the same
`SavedTranscript` source over the view's `TranscriptPresentation`. Tool calls, sent
messages, ACP agent chunks and context events reach the Qt history through the same
transcript-source pipeline Textual uses — no parallel Qt-only event wiring, no
handrolled mirror of the `TranscriptHistory` body.

Textual pairs its `TranscriptHistory` bases with Textual-widget machinery (`LineHistory`,
`Widget`, reactive). Qt pairs the same shared bases with `QtConversationHistory` (which
already composes the shared pager, read-marking and notifications). The one divergence is
the frontend-specific page container (`TranscriptPageView` vs `QtPage`); everything else —
coverage projection, commit participation, outgoing-reference tracking, source parking —
lives on the shared `CommittedHistoryBase`.
"""
from __future__ import annotations


from toad.client.committed_history import CommittedHistoryBase
from toad.client.history_coverage import ReportsCoveredPages
from toad.client.prepared_pages import PreparedTranscriptPage, UnreadTranscriptPage
from toad.qt.history import QT_FRAGMENT_CLASSES, QtConversationHistory
from toad.transcript_preparation import SavedTranscript


class QtTranscriptHistory(QtConversationHistory, CommittedHistoryBase, ReportsCoveredPages):
    """Qt history for a saved transcript: tool calls, sent messages, Claude chunks and
    bus messages all feed in through `SavedTranscript` so the ACP tab renders what
    Textual's `TranscriptHistory` renders. Same bases, same contracts, same source type;
    only the page-view container (`QtPage`) and renderer differ."""

    @classmethod
    def empty_page(cls):
        """Transcript pages, not wire pages. Mirrors Textual's
        `TranscriptHistory.empty_page` so the history starts at the right page type."""
        return PreparedTranscriptPage.empty(UnreadTranscriptPage())

    def _initial_page_source(self, prepared, app):
        """Bind a `SavedTranscript` over the view's `TranscriptPresentation`. The loader
        callable is `view.transcript.get_transcript_page`; the fragment family is
        `QT_FRAGMENT_CLASSES` (Qt-flavored siblings of the canonical neutral family —
        same decode, Qt-flavored rendering, no data duplication)."""
        return SavedTranscript(
            self.view.transcript.get_transcript_page,
            prepared.page.after,
            app.preparation,
            fragments=QT_FRAGMENT_CLASSES,
        )

