"""The thread's in-progress CLI draft under a Qt history (Textual's `CliDraft` row): the
shared `DRAFT_SUMMARY` line, hidden while no draft stands."""

from __future__ import annotations

from pyqt_reactive.widgets.fitted_text import ElidedLine

from toad.client.draft_summary import DRAFT_SUMMARY


class QtDraftLine(ElidedLine):
    def __init__(self) -> None:
        super().__init__("")
        self.hide()

    def show_draft(self, draft) -> None:
        text = DRAFT_SUMMARY.project_value(draft)
        self.setText(text or "")
        self.setVisible(text is not None)
