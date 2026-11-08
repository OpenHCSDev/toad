"""Pointer adapters for Textual's existing selection owners.

Focus owns widget-row selection; OptionList.highlighted owns virtual-row selection.
Hover is an input to those owners, never another independently rendered state.
"""

from typing import ClassVar

from rich.style import Style
from textual import events, on
from textual._paint_state import PaintState
from textual.content import Content
from textual.strip import Strip
from textual.visual import VisualType, visualize
from textual.widgets import ListItem, ListView, OptionList, Static
from ui_theme.effects import NAME_WAVE, NEW_TEXT, Band, Frame
from ui_theme.scheme import (
    BlockCursorBackgroundColour,
    BlockCursorForegroundColour,
    ThemeColour,
)

from toad.frame_presentation import Animated
from toad.tone_paint import UntintedTonePaint


class ChangingText[FrameT: Frame](Animated[FrameT], Static):
    """Changed content fades into its own colours through the shared app clock."""

    text_fades = (NEW_TEXT,)

    def update(self, content: VisualType = "", *, layout: bool | None = None) -> None:
        """New content redraws and fades in; content that draws like what is shown changes nothing,
        not even layout. A link resolved later, or a theme's new colours, keeps the text but draws
        differently."""
        markup = self._render_markup
        if self.visual.draws_like(visualize(self, content, markup)):
            return
        super().update(content, layout=layout)
        if self.is_mounted:
            for effect in self.text_fades:
                self.run_effect(effect)


class ViewLabel(Animated[Band], Static):
    """A working view waves through its own name; emphasis is independent of content fades."""

    def activity_content(self, label: Content, busy: bool, *, prefix: Content) -> Content:
        """The row's own label, working or not: being busy is drawn, never spelled.

        The spinner used to take the label's leading cell and animate a glyph where the
        status marker already sits - a working thread's label is "⌛ name" before anything
        here touches it - and it swapped the label for the bare title to make room, so the
        row's text changed every time work started or stopped and fired the content fade
        with it. Now only the wave moves.
        """
        if busy:
            if NAME_WAVE not in self.effects:
                self.run_effect(NAME_WAVE)
        else:
            self.stop_effect(NAME_WAVE)
        return Content.assemble(prefix, label)

    @property
    def current(self) -> bool:
        return False

    def render_line(self, y: int, paint: PaintState) -> Strip:
        line = super().render_line(y, paint)
        if NAME_WAVE in self.effects and y == 0:
            # The frame is a span of the line; the backend owns how a span is inked.
            line = self.effect_frame(NAME_WAVE).paint(self.app.colours, line)
        current = self.current
        return self.emphasize(line, Style(bold=current, underline=current), y)

    def emphasize(self, line: Strip, style: Style, y: int) -> Strip:
        """The whole line carries the row's current-target emphasis."""
        return line.apply_style(style)

    def paint_current(self) -> None:
        self.refresh(layout=False)


class HoverSelection(UntintedTonePaint):
    """Paint a control from native pointer/focus state, without CSS transitions."""

    highlight_foreground: ClassVar[type[ThemeColour] | None] = BlockCursorForegroundColour
    highlight_background: ClassVar[type[ThemeColour] | None] = BlockCursorBackgroundColour
    highlighted_text_style = Style()

    @property
    def text_background(self) -> type[ThemeColour]:
        return (self.highlight_background
                if self.paint_highlighted and self.highlight_background is not None
                else super().text_background)

    @property
    def paint_highlighted(self):
        return not self.disabled and (self.has_focus or self.mouse_hover)

    @property
    def paint_foreground(self):
        return (self.app.colours.colour(self.highlight_foreground)
                if self.paint_highlighted and self.highlight_foreground else None)

    @property
    def paint_background(self):
        return (self.app.colours.colour(self.highlight_background)
                if self.paint_highlighted and self.highlight_background else None)

    @property
    def paint_text_style(self):
        return self.highlighted_text_style if self.paint_highlighted else None

    def watch_mouse_hover(self):
        self.refresh_paint()


class InlineSelection(HoverSelection):
    """An inline action adds emphasis without replacing its colours."""

    highlight_foreground = highlight_background = None
    highlighted_text_style = Style(underline=True)


class ColourSelection(HoverSelection):
    """A handle changes only its ink, keeping its declared surface and text."""

    highlight_background = None


class SelectionOptionList(OptionList):
    def _on_mouse_move(self, event: events.MouseMove) -> None:
        event.prevent_default()
        self._mouse_hovering_over = None
        index = event.style.meta.get("option")
        if isinstance(index, int) and 0 <= index < self.option_count:
            if index != self.highlighted and not self.get_option_at_index(index).disabled:
                self.highlighted = index


class SelectionListItem(ListItem):
    @on(events.Enter)
    @on(events.Leave)
    def on_enter_or_leave(self, event: events.Enter | events.Leave) -> None:
        event.prevent_default()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._select_pointer()

    def _select_pointer(self) -> None:
        if isinstance(self.parent, ListView):
            self.parent.index = self.parent.children.index(self)
