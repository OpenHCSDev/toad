"""Immutable inherited paint values, resolved once per style/topology revision."""

from __future__ import annotations

from typing import NamedTuple

from rich.style import NULL_STYLE, Style

from textual.color import Color


class PaintState(NamedTuple):
    parent: PaintState | None
    style_key: int
    background: Color
    foreground: Color
    text_style: Style
    opacity: float
    base_background: Color
    layered_background: Color
    cacheable: bool = True

    def same_paint(self, other: PaintState) -> bool:
        """Compare pixels, independently of the resolver's dependency lineage.

        Ancestor visibility or layout edits require fresh dependency resolution,
        but retained paint remains valid when its resulting values are unchanged.
        """
        return (
            self.background,
            self.foreground,
            self.text_style,
            self.opacity,
            self.base_background,
            self.layered_background,
        ) == (
            other.background,
            other.foreground,
            other.text_style,
            other.opacity,
            other.base_background,
            other.layered_background,
        )


EMPTY_PAINT = PaintState(
    None, -1, Color(0, 0, 0, 0), Color(255, 255, 255, 0),
    NULL_STYLE, 1.0, Color(0, 0, 0, 0), Color(0, 0, 0, 0),
)


def resolve_paint(parent: PaintState, styles) -> PaintState:
    """Apply one declaration layer, preserving Textual's native alpha order."""
    opacity = parent.opacity * styles.opacity
    tinted = styles.background.tint(styles.background_tint)
    background = parent.background
    text_background = background
    if styles.has_rule("background"):
        text_background = background + tinted
        background += tinted.multiply_alpha(opacity)
    foreground = styles.color if styles.has_rule("color") else parent.foreground
    if styles.has_rule("auto_color") and styles.auto_color:
        foreground = text_background.get_contrast_text(foreground.a)
    return PaintState(
        parent, styles._cache_key, background, foreground,
        parent.text_style + styles.text_style, opacity,
        parent.layered_background,
        parent.layered_background + tinted.multiply_alpha(opacity),
        parent.cacheable,
    )
