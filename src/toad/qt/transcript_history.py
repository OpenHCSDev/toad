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
from toad.qt.history import QtConversationHistory
from toad.qt.transcript_fragments import QT_FRAGMENT_CLASSES
from toad.transcript_preparation import SavedTranscript


class QtTranscriptHistory(QtConversationHistory, CommittedHistoryBase, ReportsCoveredPages):
    """Qt history for a saved transcript: tool calls, sent messages, Claude chunks and
    bus messages all feed in through `SavedTranscript` so the ACP tab renders what
    Textual's `TranscriptHistory` renders. Same bases, same contracts, same source type;
    only the page-view container (`QtPage`) and renderer differ."""

    fragment_classes = QT_FRAGMENT_CLASSES

    @property
    def undrawn(self) -> bool:
        """Transcript pages carry `TranscriptCursor`, not wire `AfterMessage` cursors;
        match Textual's `TranscriptHistory` (`HistoryPager.undrawn`) so arrival capture
        never calls wire-only `.requires_read()` on `NoNativeTranscriptCursor`."""
        return not self.draws_rows

    @classmethod
    def initial_state(cls, view):
        """Start a bound thread unread, so mounting requests its first saved page.

        ``LiveTranscript`` means a page has already been published and its ``mounted``
        transition deliberately does nothing.  A restored Qt mailbox used that state for
        an empty page, so only a later send's explicit refresh made history appear.
        """
        return view.thread_identity.transcript_state()

    @classmethod
    def empty_page(cls):
        """Transcript pages, not wire pages. Mirrors Textual's
        `TranscriptHistory.empty_page` so the history starts at the right page type."""
        return PreparedTranscriptPage.empty(UnreadTranscriptPage())

    def _initial_page_source(self, prepared, app):
        """Bind a `SavedTranscript` over the view's `TranscriptPresentation`. The loader
        source is `view.transcript`, its pages and their files; the fragment family is
        `QT_FRAGMENT_CLASSES` (Qt-flavored siblings of the canonical neutral family —
        same decode, Qt-flavored rendering, no data duplication)."""
        return SavedTranscript(
            self.view.transcript,
            prepared.page.after,
            app.preparation,
            fragments=self.fragment_classes,
        )

