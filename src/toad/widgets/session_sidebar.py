"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from textual.content import Content
from agent_comms.ui_model.sidebar import ThreadRowModel

from toad.widgets.selection import HoverSelection, ViewLabel


class ThreadStatusRow(ViewLabel, HoverSelection):
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
    ThreadStatusRow:hover, ThreadStatusRow:focus {
        background: $block-cursor-background;
        color: $block-cursor-foreground !important;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and (self.action_status is not None or self.thread_row.status.busy)

    def show(self, row: ThreadRowModel, *, pinned: bool = False, action_status: str | None = None) -> None:
        """Render the model's row with this view's own decoration: pin and pending action."""
        if (row, pinned, action_status) == (self.thread_row, self.pinned, self.action_status):
            return
        self.thread_row, self.pinned, self.action_status = row, pinned, action_status
        summary = action_status if action_status is not None else row.summary
        self.update_classes({"-wire-thread": True, "-busy": self.busy, "-asking": False})
        self.tooltip = Content("\n".join(str(value) for value in (
            row.name, summary, row.unread.detail, "Pinned in this channel" if pinned else None, row.model,
        ) if value))
        badge = f"{row.unread.label} " if row.unread.label else ""
        title = self.activity_content(row.title, Content(row.label), self.busy,
                                      prefix=Content.assemble(badge, "* " if self.pinned else ""))
        content = Content.assemble(title, f"\n  {summary}")
        self.show_content(content)

    def show_content(self, content: Content, *, layout: bool = False) -> None:
        """Repaint changed native content; visibility owns label emphasis."""
        current = self.content
        if not current.is_same(content):
            self.update(content, layout=layout and current.plain != content.plain)

    def retire_thread_row(self) -> None:
        """This row no longer shows a thread."""
        self.stop_effect()
        if self.thread_row is not None:
            self.update_classes({"-wire-thread": False, "-busy": False, "-asking": False})
        self.thread_row = None
