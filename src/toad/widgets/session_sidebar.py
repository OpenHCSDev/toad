"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.content import Content
from textual import events, on
from textual.geometry import Offset
from textual.layout import WidgetPlacement
from textual.reactive import var
from ui_theme.effects import SIDEBAR_ENTER, SIDEBAR_EXIT, SIDEBAR_MOVE
from agent_comms.ui_model.sidebar import ThreadRowModel

from ui_theme.scheme import AlternateRowToneColour, BlockCursorBackgroundColour, BlockCursorForegroundColour

from toad.frame_presentation import AlternatingTonePaint
from toad.widgets.selection import HoverSelection, ViewLabel

if TYPE_CHECKING:
    from toad.app import ToadApp


class ThreadStatusRow(AlternatingTonePaint, ViewLabel, HoverSelection):
    """Compact wire status presentation shared by open and unopened threads."""

    alternate_tone = AlternateRowToneColour
    leaving = var(False)

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
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._motion_origin = Offset()
        self._motion_target = Offset()
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def highlighted(self) -> bool:
        return self.has_focus or self.mouse_hover

    @property
    def paint_background(self):
        return self.app.colours.colour(BlockCursorBackgroundColour) if self.highlighted else None

    @property
    def paint_foreground(self):
        return self.app.colours.colour(BlockCursorForegroundColour) if self.highlighted else None

    @on(events.Enter)
    @on(events.Leave)
    def hover_changed(self, event) -> None:
        if event.node is self:
            self.refresh_paint()

    def on_mount(self) -> None:
        self.run_effect(SIDEBAR_ENTER)

    def compute_disabled(self) -> bool:
        return self.leaving

    def retire(self) -> None:
        self.leaving = True
        self.run_effect(SIDEBAR_EXIT)
        self.repaint()

    @property
    def paint_opacity(self) -> float:
        return self.effect_frame(SIDEBAR_ENTER).value * (
            self.effect_frame(SIDEBAR_EXIT).value if self.leaving else 1.0)

    def pending_move(self, placement: WidgetPlacement) -> bool:
        return placement.region.offset != self._motion_target

    def place(self, placement: WidgetPlacement, shift: Offset) -> WidgetPlacement:
        if self.size and (self.pending_move(placement) or shift.y):
            self._motion_origin = self.region.offset - self.parent.content_region.offset + self.parent.scroll_offset + shift
            self.run_effect(SIDEBAR_MOVE)
        self._motion_target = placement.region.offset
        offset = self._motion_origin.blend(self._motion_target, self.effect_frame(SIDEBAR_MOVE).value) - self._motion_target
        return placement._replace(offset=placement.offset + offset)

    def repaint(self) -> None:
        if self.leaving and (not self.animation_visible
                or self.effect_frame(SIDEBAR_EXIT) == SIDEBAR_EXIT.final):
            self.remove()
            return
        moving = SIDEBAR_MOVE in self.effects
        if moving and SIDEBAR_MOVE.finished(self.effects[SIDEBAR_MOVE].elapsed):
            self.stop_effect(SIDEBAR_MOVE)
        self.refresh(layout=moving)

    def on_hide(self) -> None:
        if self.leaving:
            self.remove()

    def show(self, row: ThreadRowModel, *, pinned: bool = False) -> None:
        """Render the model's row as this app shows it: an open session's state, pin and pending action."""
        app = cast("ToadApp", self.app)
        row = app.session_navigation.thread_row(row)
        action_status = app.thread_actions.pending.get(row.name)
        if (row, pinned, action_status) == (self.thread_row, self.pinned, self.action_status):
            return
        self.thread_row, self.pinned, self.action_status = row, pinned, action_status
        summary = action_status if action_status is not None else row.summary
        busy = action_status is not None or row.status.working
        self.update_classes({"-wire-thread": True, "-busy": busy, "-asking": False})
        self.tooltip = Content("\n".join(str(value) for value in (
            row.name, summary, row.unread.detail, "Pinned in this channel" if pinned else None, row.model,
        ) if value))
        badge = f"{row.unread.label} " if row.unread.label else ""
        title = self.activity_content(row.title, Content(row.label), busy,
                                      prefix=Content.assemble(badge, "* " if self.pinned else ""))
        content = Content.assemble(title, f"\n  {summary}")
        self.update(content, layout=False)

    def retire_thread_row(self) -> None:
        """This row no longer shows a thread."""
        self.stop_effect()
        if self.thread_row is not None:
            self.update_classes({"-wire-thread": False, "-busy": False, "-asking": False})
        self.thread_row = None
