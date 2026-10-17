"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.content import Content
from textual.geometry import Offset
from ui_theme.effects import SIDEBAR_ENTER, SIDEBAR_EXIT, SIDEBAR_MOVE, Transition
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

    _row_width = 0

    def get_content_width(self, container, viewport) -> int:
        return self._row_width

    def on_mount(self) -> None:
        self.run_worker(self._measure_width(self.content), group="row-width", exclusive=True)

    def update(self, content="", *, layout=None) -> None:
        previous = self.content
        super().update(content, layout=layout)
        if self.is_mounted and previous.plain != self.content.plain:
            self.run_worker(self._measure_width(self.content), group="row-width", exclusive=True)

    async def _measure_width(self, content: Content) -> None:
        width = await self.app.preparation.run_thread(content.get_optimal_width, {}, 0)
        if self.content.plain == content.plain:
            self._row_width = width
            self.refresh(layout=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._motion_origin = Offset()
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    def painted_position(self) -> Offset:
        return (self.region.offset - self.parent.content_region.offset
                + self.parent.scroll_offset)

    def slide(self, owner, origin: Offset) -> None:
        self._motion_origin = origin
        self.run_effect(SIDEBAR_MOVE, target=owner)

    def disappear(self, owner) -> None:
        self._motion_origin = self.painted_position()
        self.disabled = True
        self.styles.position = "absolute"
        self.run_effect(SIDEBAR_EXIT, target=owner)

    @property
    def paint_opacity(self) -> float:
        return (self.effect_frame(SIDEBAR_ENTER).value
                if SIDEBAR_ENTER in self.effects else 1.0) * (
                    self.effect_frame(SIDEBAR_EXIT).value if SIDEBAR_EXIT in self.effects else 1.0)

    def place(self, placement):
        if SIDEBAR_EXIT in self.effects:
            return placement._replace(region=placement.region.at_offset(self._motion_origin))
        if SIDEBAR_MOVE not in self.effects:
            return placement
        frame = self.effect_frame(SIDEBAR_MOVE)
        destination = placement.region.offset
        offset = Offset(round(frame.displacement(self._motion_origin.x, destination.x)),
                        round(frame.displacement(self._motion_origin.y, destination.y)))
        return placement._replace(offset=placement.offset + offset)

    def refresh_motion(self) -> None:
        if not any(isinstance(effect, Transition) for effect in self.effects):
            return
        if SIDEBAR_EXIT in self.effects and SIDEBAR_EXIT.finished(self.effects[SIDEBAR_EXIT].elapsed):
            self.remove()
            return
        for effect in (SIDEBAR_ENTER, SIDEBAR_MOVE):
            if effect in self.effects and effect.finished(self.effects[effect].elapsed):
                self.stop_effect(effect)
        self.refresh()

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
