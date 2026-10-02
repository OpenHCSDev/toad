"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from toad.widgets.selection import HoverSelection
from toad.sidebar_preparation import PreparedThreadRow, ThreadRowInput


class ThreadStatusRow(HoverSelection):
    """Compact wire status presentation shared by open and unopened threads."""

    DEFAULT_CSS = """
    ThreadStatusRow.-wire-thread {
        height: 2;
        padding: 0;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        color: $text-muted;
        pointer: pointer;
    }
    ThreadStatusRow.-wire-thread.-busy { color: $warning; }
    ThreadStatusRow.-wire-thread.-unread { text-style: bold; }
    ThreadStatusRow:hover {
        background: transparent;
        color: #ad8bf5 !important;
        text-style: underline;
    }
    ThreadStatusRow:ansi:hover {
        background: transparent;
        color: ansi_magenta !important;
        text-style: underline;
    }
    ThreadStatusRow:focus {
        background: transparent;
        color: #ad8bf5 !important;
        text-style: underline;
    }
    ThreadStatusRow:ansi:focus {
        background: transparent;
        color: ansi_magenta !important;
        text-style: underline;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_signature: tuple | None = None
        self.thread_name: str | None = None
        self._spinner_phase = 0
        self._thread_presentation: PreparedThreadRow | None = None

    def advance_spinner(self, phase: int) -> None:
        if self._spinner_phase == phase or not self.has_class("-busy"):
            return
        self._spinner_phase = phase
        if self._thread_presentation is not None:
            self.paint_thread_frame(self._thread_presentation)

    def thread_preparation(self, source: ThreadRowInput) -> PreparedThreadRow | None:
        """Reuse this row's rendered resource for its exact authored inputs."""
        prepared = self._thread_presentation
        if prepared is not None and prepared.source == source.presentation():
            return prepared
        return None

    def apply_thread_preparation(self, prepared: PreparedThreadRow) -> None:
        if self._thread_presentation is prepared:
            return
        self._thread_presentation = prepared
        source = prepared.source
        self.thread_name = source.name
        self.update_classes({"-wire-thread": True, "-busy": prepared.busy,
                             "-unread": source.unread.highlighted, "-asking": False})
        self.tooltip = prepared.tooltip
        self.paint_thread_frame(prepared)

    def retire_thread_preparation(self) -> None:
        """Release row output when its source becomes unavailable."""
        if self._thread_presentation is not None:
            self.update_classes({"-wire-thread": False, "-busy": False,
                                 "-unread": False, "-asking": False})
        self._thread_presentation = None
        self._thread_signature = None

    def paint_thread_frame(self, prepared: PreparedThreadRow) -> None:
        """Paint a prepared frame without repeating source publication."""
        signature = (prepared.signature, self._spinner_phase % len(prepared.frames))
        if signature == self._thread_signature:
            return
        self._thread_signature = signature
        self.update(prepared.content(self._spinner_phase), layout=False)
