from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, NamedTuple

from textual.geometry import Size, Spacing
from textual.css.scalar import Scalar

if TYPE_CHECKING:
    from textual.widget import Widget
    from textual.document._paint import DocumentNode
    from textual._extrema import Extrema


class BoxModel(NamedTuple):
    """The result of `get_box_model`."""

    # Content + padding + border
    width: Fraction
    height: Fraction
    margin: Spacing  # Additional margin

    @classmethod
    def resolve(
        cls,
        node: Widget | DocumentNode,
        container: Size,
        viewport: Size,
        width_fraction: Fraction,
        height_fraction: Fraction,
        constrain_width: bool = False,
        greedy: bool = True,
    ) -> tuple[BoxModel, Extrema]:
        """Resolve native CSS dimensions from intrinsic measurements.

        Scene custody and measurement reuse belong to the caller. The actual
        border-box, auto dimensions, fraction and extrema algorithm is shared
        by mounted widgets and detached native document nodes.
        """
        styles = node.styles
        is_border_box = styles.box_sizing == "border-box"
        gutter = styles.gutter  # Padding plus border
        margin = styles.margin

        styles_width = styles.width
        if not greedy and styles_width is not None and styles_width.is_fraction:
            styles_width = Scalar.parse("auto")
        is_auto_width = styles_width and styles_width.is_auto
        is_auto_height = styles.height and styles.height.is_auto

        # Container minus padding and border
        content_container = container - gutter.totals

        extrema = node._extrema = node._resolve_extrema(
            container, viewport, width_fraction, height_fraction
        )
        min_width, max_width, min_height, max_height = extrema

        if styles_width is None:
            # No width specified, fill available space
            content_width = Fraction(content_container.width - margin.width)
        elif is_auto_width:
            # When width is auto, we want enough space to always fit the content
            content_width = Fraction(
                node.get_content_width(content_container - margin.totals, viewport)
            )
            if (
                styles.overflow_x == "auto" and styles.scrollbar_gutter == "stable"
            ) or node.show_vertical_scrollbar:
                content_width += styles.scrollbar_size_vertical
            if (
                content_width < content_container.width
                and node._has_relative_children_width
            ):
                content_width = Fraction(content_container.width)
        else:
            # An explicit width
            content_width = styles_width.resolve(
                container - margin.totals, viewport, width_fraction
            )
            if is_border_box:
                content_width -= gutter.width

        if min_width is not None:
            # Restrict to minimum width, if set
            content_width = max(content_width, min_width, Fraction(0))

        if max_width is not None and not (
            container.width == 0
            and not styles.max_width.is_cells
            and node._parent is not None
            and node._parent.styles.is_auto_width
        ):
            # Restrict to maximum width, if set
            content_width = min(content_width, max_width)

        content_width = max(Fraction(0), content_width)

        if constrain_width:
            content_width = min(Fraction(container.width - gutter.width), content_width)

        if styles.height is None:
            # No height specified, fill the available space
            content_height = Fraction(content_container.height - margin.height)
        elif is_auto_height:
            # Calculate dimensions based on content
            content_height = Fraction(
                node.get_content_height(
                    content_container - margin.totals,
                    viewport,
                    int(content_width),
                )
            )
            if (
                styles.overflow_y == "auto" and styles.scrollbar_gutter == "stable"
            ) or node.show_horizontal_scrollbar:
                content_height += styles.scrollbar_size_horizontal
            if (
                content_height < content_container.height
                and node._has_relative_children_height
            ):
                content_height = Fraction(content_container.height)
        else:
            styles_height = styles.height
            # Explicit height set
            content_height = styles_height.resolve(
                container - margin.totals, viewport, height_fraction
            )
            if is_border_box:
                content_height -= gutter.height

        if min_height is not None:
            # Restrict to minimum height, if set
            content_height = max(content_height, min_height, Fraction(0))

        if max_height is not None and not (
            container.height == 0
            and not styles.max_height.is_cells
            and node._parent is not None
            and node._parent.styles.is_auto_height
        ):
            content_height = min(content_height, max_height)

        content_height = max(Fraction(0), content_height)
        model = cls(
            content_width + gutter.width, content_height + gutter.height, margin
        )
        return model, extrema
