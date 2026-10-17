"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from math import prod

from textual.content import Content
from textual.geometry import Offset
from textual.layout import WidgetPlacement
from toad.widgets.sidebar_viewport import SidebarViewport
from ui_theme.effects import SIDEBAR_ENTER, SIDEBAR_EXIT, SIDEBAR_MOVE
from agent_comms.ui_model.sidebar import ThreadRowModel

from ui_theme.scheme import AlternateRowToneColour

from toad.frame_presentation import AlternatingTonePaint
from toad.widgets.selection import HoverSelection, ViewLabel

if TYPE_CHECKING:
    from toad.app import ToadApp


class ThreadStatusRow(AlternatingTonePaint, ViewLabel, HoverSelection):
    """Compact wire status presentation shared by open and unopened threads."""

    alternate_tone = AlternateRowToneColour

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
        self._motion_origin = Offset()
        self._motion_target = Offset()
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    def on_mount(self) -> None:
        self.run_effect(SIDEBAR_ENTER)

    def retire(self) -> None:
        self.disabled = True
        self.run_effect(SIDEBAR_EXIT)
        self.repaint()

    @property
    def paint_opacity(self) -> float:
        return prod(self.effect_frame(effect).value for effect in (SIDEBAR_ENTER, SIDEBAR_EXIT)
                    if effect in self.effects)

    def pending_move(self, placement: WidgetPlacement) -> bool:
        return placement.region.offset != self._motion_target

    def preserve_reader(self, placement: WidgetPlacement, viewport: SidebarViewport) -> Offset:
        if not self.pending_move(placement):
            return Offset()
        before = viewport.scroll_y
        viewport.scroll_y += placement.region.y - self._motion_target.y
        shift = viewport.scroll_y - before
        viewport.app.animator.transform_running_animation(viewport, "scroll_y", lambda value: value + shift)
        viewport.scroll_target_y += shift
        return Offset(0, round(shift))

    def place(self, placement: WidgetPlacement, shift: Offset) -> WidgetPlacement:
        if self.size and (self.pending_move(placement) or shift.y):
            self._motion_origin = self.region.offset - self.parent.content_region.offset + self.parent.scroll_offset + shift
            self.run_effect(SIDEBAR_MOVE)
        self._motion_target = placement.region.offset
        offset = self._motion_origin.blend(self._motion_target, self.effect_frame(SIDEBAR_MOVE).value) - self._motion_target
        return placement._replace(offset=placement.offset + offset)

    def repaint(self) -> None:
        if SIDEBAR_EXIT in self.effects and (not self.app.colours.clock.enabled
                or not self.animation_visible or SIDEBAR_EXIT.finished(self.effects[SIDEBAR_EXIT].elapsed)):
            self.remove()
            return
        moving = SIDEBAR_MOVE in self.effects
        if moving and SIDEBAR_MOVE.finished(self.effects[SIDEBAR_MOVE].elapsed):
            self.stop_effect(SIDEBAR_MOVE)
        self.refresh(layout=moving)

    def on_hide(self) -> None:
        if SIDEBAR_EXIT in self.effects:
            self.remove()

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and (self.action_status is not None or self.thread_row.status.working)

    def show(self, row: ThreadRowModel, *, pinned: bool = False) -> None:
        """Render the model's row as this app shows it: an open session's state, pin and pending action."""
        app = cast("ToadApp", self.app)
        row = app.session_navigation.thread_row(row)
        action_status = app.thread_actions.pending.get(row.name)
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
        self.update(content, layout=False)

    def retire_thread_row(self) -> None:
        """This row no longer shows a thread."""
        self.stop_effect()
        if self.thread_row is not None:
            self.update_classes({"-wire-thread": False, "-busy": False, "-asking": False})
        self.thread_row = None
