from __future__ import annotations

from typing import ClassVar

from textual.content import Content
from textual.css.native import NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.geometry import Size
from textual.style import Style
from textual.widgets import Static
from ui_theme.effects import Wipe, Band
from ui_theme.scheme import AccentColour, PrimaryColour

from toad.frame_presentation import Animated
from toad.native_style import AutoWidth, NoWrap, OneRow


class FutureText(AutoWidth, OneRow, NoWrap, Animated[Band], Static):
    """Reveal one text from elapsed time, then leave it still."""

    native_theme = (NativeDeclaration.of(Styles.color, Variable(PrimaryColour.name)),)
    ALLOW_SELECT = False
    BARS: ClassVar[list[str]] = ["▉", "▊", "▋", "▌", "▍", "▎", "▏", " "]

    def __init__(self, text: Content, *, speed: float = 16.0):
        self.text = text
        length = len(text) + 1
        self.effect = Wipe(AccentColour, width=1 / length,
                           duration=(length + 1) / speed, frames_per_second=60)
        super().__init__()

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "center"

    def on_mount(self) -> None:
        self.run_effect(self.effect)

    def get_content_width(self, container: Size, viewport: Size) -> int:
        return self.text.cell_length

    def render(self) -> Content:
        frame = self.effect_frame(self.effect)
        if frame.start == frame.end:
            return self.text
        progress, fraction = divmod(frame.end * (len(self.text) + 1), 1)
        text = self.text[:int(progress)]
        if progress < 1:
            return text
        cursor = self.BARS[7 - int(fraction * 8)]
        style = Style(foreground=self.app.colours.colour(frame.colour))
        return Content.assemble(text, (cursor, style + Style(reverse=True)),
                                (cursor, style), " " * (len(self.text) + 1 - len(text)))
