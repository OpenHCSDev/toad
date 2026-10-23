"""Widgets paint their area on a declared theme tone, under their own CSS paint."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual._paint_state import PaintLayer
from textual.color import TRANSPARENT, Color
from ui_theme.scheme import BackgroundColour, ThemeColour

if TYPE_CHECKING:
    from textual.css.styles import StylesBase


class ToneLayer(PaintLayer):
    """A widget's own CSS paint laid over its area tone.

    CSS backgrounds (hover, selection, transparency) compose over the tone by
    alpha; with no tone the CSS paint is unchanged.
    """

    __slots__ = (
        "styles",
        "paint_background",
        "paint_foreground",
        "auto_color",
        "layer_opacity",
        "text_style",
        "background_tint",
    )

    def __init__(self, styles: StylesBase, tone: Color | None, opacity: float, paint: TonePaint) -> None:
        self.styles = styles
        self.layer_opacity = styles.layer_opacity * opacity
        stated = paint.paint_background
        if stated is None:
            stated = styles.paint_background
        foreground = paint.paint_foreground
        self.paint_foreground = styles.paint_foreground if foreground is None else foreground
        self.auto_color = styles.auto_color if foreground is None else foreground.auto
        text_style = paint.paint_text_style
        self.text_style = styles.text_style if text_style is None else text_style
        tint = paint.background_tint
        self.background_tint = styles.background_tint if tint is None else tint
        self.paint_background = stated if tone is None else tone if stated is None else tone + stated

    text_opacity = property(lambda self: self.styles.text_opacity)


class TonePaint:
    """Paints a screen area on its declared theme tone; ``None`` keeps the parent's."""

    tone: ClassVar[type[ThemeColour] | None] = None
    paint_background = paint_foreground = paint_text_style = background_tint = None
    paint_opacity = 1.0

    @property
    def text_background(self) -> type[ThemeColour]:
        return BackgroundColour if self.tone is None else self.tone

    @property
    def paint_layer(self) -> PaintLayer:
        tone = self.tone
        return ToneLayer(self.styles, None if tone is None else self.app.colours.colour(tone), self.paint_opacity, self)


class UntintedTonePaint(TonePaint):
    """Keep the parent's area tone without an additional focus tint."""

    background_tint = TRANSPARENT
