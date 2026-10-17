"""Native form geometry and paint, supplied directly to Textual's owners."""
from __future__ import annotations

from textual.binding import Binding
from textual.color import Color, TRANSPARENT
from textual.css._style_properties import Edges
from textual.css.scalar import Scalar
from textual.geometry import Spacing
from textual.layouts.horizontal import HorizontalLayout
from textual.widgets._select import SelectCurrent
from textual.widgets import Checkbox, Input
from ui_theme.scheme import BackgroundColour, ErrorColour, ForegroundColour, PrimaryColour, SurfaceColour
from toad.widget_view import AUTO, FocusWithinView, WidgetView
from toad.screens.modal import ModalScreen


class FramedControl(FocusWithinView):
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


class FormModal[Result](WidgetView, ModalScreen[Result]):
    """Shared native modal presentation and theme invalidation lifecycle."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    height = None
    align_horizontal = "center"
    align_vertical = "middle"

    @property
    def paint_background(self) -> Color:
        return self.app.colours.colour(BackgroundColour).multiply_alpha(0.6)

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self.theme_changed)

    def theme_changed(self, theme) -> None:
        # A theme changes the entire visible modal, not each offscreen field.
        self.refresh()

    def action_cancel(self) -> None:
        self.dismiss(None)
