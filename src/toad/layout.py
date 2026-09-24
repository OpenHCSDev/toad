"""Layout policies that don't require order-sensitive CSS invalidation."""

from textual.geometry import Spacing
from textual.layout import WidgetPlacement


def trim_trailing_margin(placements: list[WidgetPlacement]) -> list[WidgetPlacement]:
    if placements:
        last = placements[-1]
        top, right, _, left = last.margin
        placements[-1] = last._replace(margin=Spacing(top, right, 0, left))
    return placements
