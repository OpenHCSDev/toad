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
from ui_theme.scheme import BlockCursorForegroundColour, BlockCursorBackgroundColour
from textual.visual import VisualType

from toad.frame_presentation import Animated, TonePaint
from textual.color import Color
from rich.style import Style
from textual.message import Message
from textual.widgets import ListItem, ListView, OptionList, Static


class ChangingText[FrameT: Frame](Animated[FrameT], Static):
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


class FocusSelection(Static, can_focus=True):
    _pointer_focus = False

    def on_mouse_move(self, event: events.MouseMove) -> None:
        # Enter can be synthesized when layout changes beneath a stationary
        # pointer. Only actual pointer input may take focus from the composer.
        self._pointer_focus = True
        if not self.has_focus:
            self.focus(scroll_visible=False)

    def on_leave(self, event: events.Leave) -> None:
        if self._pointer_focus and self.has_focus:
            self.blur()
        self._pointer_focus = False

    def on_key(self, event: events.Key) -> None:
        self._pointer_focus = False


class HoverSelection(TonePaint):
    """Paint a control from native pointer/focus state, without CSS transitions."""

    tone = None
    highlight_foreground = BlockCursorForegroundColour.name
    highlight_background = BlockCursorBackgroundColour.name

    @property
    def paint_highlighted(self):
        return self.has_focus or self.mouse_hover

    @property
    def highlighted_text_style(self):
        return Style.parse(self.app.colours.variables["block-cursor-text-style"])

    @property
    def paint_foreground(self):
        return (Color.parse(self.app.colours.variables[self.highlight_foreground])
                if self.paint_highlighted and self.highlight_foreground else None)

    @property
    def paint_background(self):
        return (Color.parse(self.app.colours.variables[self.highlight_background])
                if self.paint_highlighted and self.highlight_background else None)

    @property
    def text_style(self):
        return self.highlighted_text_style if self.paint_highlighted else None

    def watch_mouse_hover(self):
        self.refresh_paint()


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
