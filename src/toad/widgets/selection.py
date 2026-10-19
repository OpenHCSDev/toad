"""Pointer adapters for Textual's existing selection owners.

Focus owns widget-row selection; OptionList.highlighted owns virtual-row selection.
Hover is an input to those owners, never another independently rendered state.
"""

from textual import events, on
from rich.segment import Segment
from textual.content import Content
from textual._paint_state import PaintState
from textual.strip import Strip
from ui_theme.effects import NEW_TEXT, SPINNER, Frame, TextFrame
from ui_theme.scheme import ThemeColour, BlockCursorForegroundColour, BlockCursorBackgroundColour
from typing import ClassVar
from textual.visual import VisualType

from toad.frame_presentation import Animated, UntintedTonePaint
from rich.style import Style
from textual.message import Message
from textual.widgets import ListItem, ListView, OptionList, Static


class ChangingText[FrameT: Frame](UntintedTonePaint, Animated[FrameT], Static):
    """Changed content fades into its own colours through the shared app clock."""

    text_fades = (NEW_TEXT,)

    def update(self, content: VisualType = "", *, layout: bool | None = None) -> None:
        if self.content == content:
            return
        super().update(content, layout=layout)
        if self.is_mounted:
            self.run_effect(NEW_TEXT)


class ViewLabel(ChangingText[TextFrame]):
    """Native label paint: workspace emphasis and clock-driven activity ink."""

    def activity_content(self, title: str, label: Content, busy: bool, *, prefix: Content) -> Content:
        """One activity slot, before decorations; idle keeps its declared marker."""
        if not busy:
            self.stop_effect(SPINNER)
            return Content.assemble(prefix, label)
        if SPINNER not in self.effects:
            self.run_effect(SPINNER)
        return Content.assemble(SPINNER.final.paint(self.app.colours, None), " ", prefix, title)

    @property
    def current(self) -> bool:
        return False

    def render_line(self, y: int, paint: PaintState) -> Strip:
        line = super().render_line(y, paint)
        if SPINNER in self.effects and y == 0:
            glyph = self.effect_frame(SPINNER).paint(self.app.colours, None)
            style = next((segment.style for segment in line), None)
            # Native clipping owns empty or partial lines.
            line = Strip.join((Strip([Segment(glyph.plain, style)], glyph.cell_length),
                               line.crop(glyph.cell_length))).crop(0, line.cell_length)
        current = self.current
        return line.apply_style(Style(bold=current, underline=current))

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
    def text_style(self):
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
    class PointerSelected(Message):
        pass

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        event.prevent_default()
        self._mouse_hovering_over = None
        index = event.style.meta.get("option")
        if isinstance(index, int) and 0 <= index < self.option_count:
            if index != self.highlighted and not self.get_option_at_index(index).disabled:
                self.highlighted = index
                self.post_message(self.PointerSelected())


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
