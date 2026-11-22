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
from ui_theme.effects import NEW_TEXT, Band, Frame
from ui_theme.scheme import (
    BlockCursorBackgroundColour,
    BlockCursorForegroundColour,
    ThemeColour,
)

from toad.client.name_wave import NameWave
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


class ViewLabel(NameWave, Animated[Band], Static):
    """A working view waves through its own name (the shared `NameWave`); emphasis is
    independent of content fades."""

    def wave_running(self) -> bool:
        return self.name_wave in self.effects

    def start_wave(self) -> None:
        self.run_effect(self.name_wave)

    def stop_wave(self) -> None:
        self.stop_effect(self.name_wave)

    def wave_cells(self) -> tuple[int, int] | None:
        """The wave's cells in this terminal row."""
        return self.band_cells(self.effect_frame(self.name_wave), self.size.width)

    def repaint_wave(self) -> None:
        """Paint the rows this view's name occupies."""
        self.repaint_lines()

    def redraw(self) -> None:
        """A wave repaints only when its band reaches different terminal cells."""
        wave_only = self.wave_running() and not any(
            self.effect_phase(fade).in_motion for fade in self.text_fades
        )
        if wave_only:
            self.wave_frame_drawn()
            return
        super().redraw()

    def activity_content(self, label: Content, busy: bool, *, prefix: Content) -> Content:
        """The row's own label, working or not: the typed status starts the wave without
        changing the label or firing a content fade. The shared app clock owns its frames."""
        self.follow_activity(busy)
        return Content.assemble(prefix, label)

    @property
    def current(self) -> bool:
        return False

    def render_line(self, y: int, paint: PaintState) -> Strip:
        line = super().render_line(y, paint)
        if self.wave_running() and y == 0:
            # The frame is a span of the line; the backend owns how a span is inked.
            line = self.effect_frame(self.name_wave).paint(self.app.colours, line)
        current = self.current
        return self.emphasize(line, Style(bold=current or self.name_bold(), underline=current), y)

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
    @on(events.MouseMove)
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

    @on(events.MouseMove)
    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._select_pointer()

    def _select_pointer(self) -> None:
        if isinstance(self.parent, ListView):
            self.parent.index = self.parent.children.index(self)
