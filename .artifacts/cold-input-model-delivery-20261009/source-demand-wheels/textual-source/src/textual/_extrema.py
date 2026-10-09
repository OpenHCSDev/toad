from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, NamedTuple

from textual.geometry import Size

if TYPE_CHECKING:
    from textual.css.styles import StylesBase


class Extrema(NamedTuple):
    """Specifies minimum and maximum dimensions."""

    min_width: Fraction | None = None
    max_width: Fraction | None = None
    min_height: Fraction | None = None
    max_height: Fraction | None = None

    def apply_width(self, width: Fraction) -> Fraction:
        """Apply width extrema.

        Args:
            width: Width value.

        Returns:
            Width, clamped between minimum and maximum.

        """
        min_width, max_width = self[:2]
        if min_width is not None:
            width = max(width, min_width)
        if max_width is not None:
            width = min(width, max_width)
        return width

    def apply_height(self, height: Fraction) -> Fraction:
        """Apply height extrema.

        Args:
            height: Height value.

        Returns:
            Height, clamped between minimum and maximum.

        """
        min_height, max_height = self[2:]
        if min_height is not None:
            height = max(height, min_height)
        if max_height is not None:
            height = min(height, max_height)
        return height

    def apply_dimensions(self, width: int, height: int) -> Size:
        """Apply extrema to integer dimensions.

        Args:
            width: Integer width.
            height: Integer height.

        Returns:
            Size with extrema applied.
        """
        return Size(
            int(self.apply_width(Fraction(width))),
            int(self.apply_height(Fraction(height))),
        )

    @classmethod
    def resolve(
        cls, styles: StylesBase, container: Size, viewport: Size,
        width_fraction: Fraction, height_fraction: Fraction,
    ) -> Extrema:
        """Resolve native min/max rules independently of scene custody."""
        min_width: Fraction | None = None
        max_width: Fraction | None = None
        min_height: Fraction | None = None
        max_height: Fraction | None = None

        container -= styles.margin.totals
        if styles.box_sizing == "border-box":
            gutter_width, gutter_height = styles.gutter.totals
        else:
            gutter_width = gutter_height = 0

        if styles.min_width is not None:
            min_width = (
                styles.min_width.resolve(container, viewport, width_fraction)
                - gutter_width
            )

        if styles.max_width is not None:
            max_width = (
                styles.max_width.resolve(container, viewport, width_fraction)
                - gutter_width
            )
        if styles.min_height is not None:
            min_height = (
                styles.min_height.resolve(container, viewport, height_fraction)
                - gutter_height
            )

        if styles.max_height is not None:
            max_height = (
                styles.max_height.resolve(container, viewport, height_fraction)
                - gutter_height
            )

        extrema = cls(min_width, max_width, min_height, max_height)
        return extrema
