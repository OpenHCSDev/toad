"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from textual.content import Content

from agent_comms.ui_model.sidebar import ThreadRowModel

from toad.widgets.activity_spinner import animated_label
from toad.widgets.selection import HoverSelection


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
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and (self.action_status is not None or self.thread_row.busy)

    def show(self, row: ThreadRowModel, *, pinned: bool = False, action_status: str | None = None) -> None:
        """Render the model's row with this view's own decoration: pin and pending action."""
        if (row, pinned, action_status) == (self.thread_row, self.pinned, self.action_status):
            return
        self.thread_row, self.pinned, self.action_status = row, pinned, action_status
        summary = action_status if action_status is not None else row.summary
        self.update_classes({"-wire-thread": True, "-busy": self.busy,
                             "-unread": row.unread.highlighted, "-asking": False})
        self.tooltip = Content("\n".join(str(value) for value in (
            row.name, summary, row.unread.detail, "Pinned in this channel" if pinned else None, row.model,
        ) if value))
        self.app.busy_rows.track(self, self.busy)
        self.paint()

    def paint(self) -> None:
        """Paint the current spinner frame; the frame is a function of time."""
        row = self.thread_row
        assert row is not None
        summary = self.action_status if self.action_status is not None else row.summary
        badge = f"{row.unread.label} " if row.unread.label else ""
        content = Content.assemble(
            (badge, "bold"),
            f"{'* ' if self.pinned else ''}"
            f"{animated_label(row.label, busy=row.busy, phase=self.app.busy_rows.phase)}"
            f"\n  {summary}",
        )
        current = self.content
        if not isinstance(current, Content) or not current.is_same(content):
            self.update(content, layout=False)

    def retire_thread_row(self) -> None:
        """This row no longer shows a thread."""
        if self.thread_row is not None:
            self.update_classes({"-wire-thread": False, "-busy": False,
                                 "-unread": False, "-asking": False})
            self.app.busy_rows.track(self, False)
        self.thread_row = None

    def on_unmount(self) -> None:
        self.app.busy_rows.track(self, False)
