"""Native widget geometry and paint declared by their owning view."""
from __future__ import annotations

from textual import events
from textual._paint_state import PaintLayer
from textual._styles_cache import FramePaint
from textual.box_model import DEFAULT_LAYER, BoxGeometry
from textual.color import TRANSPARENT
from textual.css._style_properties import Edges
from textual.css.scalar import Scalar, ScalarOffset, Unit
from textual.geometry import Spacing

AUTO = Scalar(1.0, Unit.AUTO, Unit.AUTO)
FILL = Scalar(1.0, Unit.FRACTION, Unit.WIDTH)


class WidgetView(BoxGeometry, PaintLayer, FramePaint):
    """The view supplies native inputs directly, without a CSS declaration mirror."""

    width = None
    height = AUTO
    min_width = min_height = max_width = max_height = None
    padding = margin = Spacing(0, 0, 0, 0)
    border = outline = Edges(*(("", TRANSPARENT),) * 4)
    box_sizing = "border-box"
    width_policy = "greedy"
    dock = split = "none"
    overflow_x = overflow_y = "hidden"
    scrollbar_policy = "auto"
    vertical_scrollbar_size = 2
    horizontal_scrollbar_size = 1
    scrollbar_visibility = "visible"
    align_horizontal = "left"
    align_vertical = "top"
    grid_rows = grid_columns = ()
    grid_size_columns = 1
    grid_size_rows = grid_gutter_horizontal = grid_gutter_vertical = 0
    row_span = column_span = 1
    keyline = ("none", TRANSPARENT)
    position = "relative"
    overlay = constrain_x = constrain_y = "none"
    child_layout = None
    placement_offset = None
    layer_name = DEFAULT_LAYER
    layer_order = None

    tint = TRANSPARENT
    hatch = None
    border_title_align = "left"
    border_subtitle_align = "right"

    @property
    def geometry(self) -> BoxGeometry:
        return self

    @property
    def frame_paint(self) -> FramePaint:
        return self

    @property
    def paint_gutter(self) -> Spacing:
        return self.box_gutter

    def set_placement_offset(self, offset: ScalarOffset) -> None:
        self.placement_offset = offset
        self.refresh(layout=True)


class FocusWithinView(WidgetView):
    """A view whose declared paint depends on focus within its descendants."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listen(events.DescendantFocus, self.refresh_paint)
        self.listen(events.DescendantBlur, self.refresh_paint)
