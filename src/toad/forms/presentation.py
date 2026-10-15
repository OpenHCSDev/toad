"""Native form geometry and paint, supplied directly to Textual's owners."""
from __future__ import annotations

from rich.style import NULL_STYLE
from textual import events
from textual._paint_state import PaintLayer
from textual._styles_cache import FramePaint
from textual.box_model import BoxGeometry
from textual.color import Color, TRANSPARENT
from textual.css._style_properties import Edges
from textual.css.scalar import Scalar, ScalarOffset, Unit
from textual.geometry import Spacing
from textual.layouts.horizontal import HorizontalLayout
from textual.widgets._select import SelectCurrent
from textual.widgets import Checkbox, Input
from ui_theme.scheme import BackgroundColour, ErrorColour, ForegroundColour, PrimaryColour, SurfaceColour


AUTO = Scalar(1.0, Unit.AUTO, Unit.AUTO)


class FormPart(BoxGeometry, PaintLayer, FramePaint):
    """The widget itself supplies native inputs; there is no styles mirror.

    Mutable state remains on the native control. Non-versioned paint inputs
    are read live instead of being cached under an unrelated CSS generation.
    The existing line cache still retains rendered strips and checks its inputs.
    """

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
    layer_name = "default"
    layer_order = None

    paint_foreground = paint_background = None
    background_tint = tint = TRANSPARENT
    text_style = NULL_STYLE
    text_opacity = layer_opacity = 1.0
    auto_color = False
    paint_key = None
    paint_cacheable = False
    hatch = None
    border_title_align = "left"
    border_subtitle_align = "right"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listen(events.DescendantFocus, self.focus_changed)
        self.listen(events.DescendantBlur, self.focus_changed)

    @property
    def geometry(self) -> BoxGeometry:
        return self

    @property
    def paint_layer(self) -> PaintLayer:
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

    def focus_changed(self, event) -> None:
        self.refresh_paint()


class FramedControl(FormPart):
    height = Scalar.from_number(3)
    padding = Spacing(0, 2, 0, 2)
    horizontal_scrollbar_size = 0

    @property
    def control_focused(self) -> bool:
        return self.has_focus or self.has_focus_within

    @property
    def border_colour(self) -> Color:
        return (self.app.colours.colour(PrimaryColour) if self.control_focused
                else Color(0, 0, 0, 0.2))

    @property
    def border(self) -> Edges:
        return Edges(*(("tall", self.border_colour),) * 4)

    @property
    def background_tint(self) -> Color:
        return (self.app.colours.colour(ForegroundColour).multiply_alpha(0.05)
                if self.control_focused else TRANSPARENT)

    @property
    def paint_background(self) -> Color:
        return self.app.colours.colour(SurfaceColour)


class FormInput(FramedControl, Input):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listen(Input.Changed, self.validation_changed)

    def validation_changed(self, message: Input.Changed) -> None:
        self.refresh_paint()

    @property
    def border_colour(self) -> Color:
        return (super().border_colour if self.is_valid else
                self.app.colours.colour(ErrorColour).multiply_alpha(0.6))


class FormCheckbox(FramedControl, Checkbox):
    width = AUTO
    padding = Spacing(0, 1, 0, 1)


class FormSelectCurrent(FramedControl, SelectCurrent):
    """The existing Select owns interaction; its current-value child owns its frame."""

    DEFAULT_LAYOUT = HorizontalLayout
    height = AUTO

    @property
    def control_focused(self) -> bool:
        return self.parent.has_focus or self.parent.has_focus_within


class FormModal(FormPart):
    """Shared native modal presentation and theme invalidation lifecycle."""

    height = None
    align_horizontal = "center"
    align_vertical = "middle"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.listen(events.Mount, self.follow_theme)

    @property
    def paint_background(self) -> Color:
        return self.app.colours.colour(BackgroundColour).multiply_alpha(0.6)

    def follow_theme(self, event: events.Mount) -> None:
        self.app.theme_changed_signal.subscribe(self, self.theme_changed)

    def theme_changed(self, theme) -> None:
        # A theme changes the entire visible modal, not each offscreen field.
        self.refresh()
