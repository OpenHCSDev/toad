"""The settings form: every setting the user may edit, searched by its label."""

from __future__ import annotations

from collections.abc import Iterable

from textual import containers, events
from textual.app import ComposeResult
from textual.binding import ModeBinding
from textual.document._editing import EditingMode
from textual.widgets import Input
from toad.widgets.footer import ToadFooter
from textual.geometry import Spacing
from textual.color import Color

from toad.app import ScreenWidth
from toad.forms.editors import SelectEditor
from toad.forms.form_view import FormView
from toad.forms.presentation import FormInput, FormModal
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import PriorityActions
from toad.widget_view import WidgetView
from toad.setting_choices import SchemeName
from toad.widget_view import ToadHosted


class SchemeEditor(ToadHosted, SelectEditor):
    """A colour scheme's name, picked from the schemes the running app has."""

    shows = (SchemeName,)

    def options(self) -> Iterable[tuple[str, object]]:
        return ((name, name) for name in self.app.colours.schemes)


class SettingsPanel(WidgetView, containers.Vertical):
    """The side of the screen the settings are shown in."""

    height = None
    padding = Spacing(0, 1, 0, 1)
    paint_background = Color(0, 0, 0, 0.1)

    @property
    def width(self):
        return ScreenWidth(self.screen.horizontal_breakpoint).side_panel_width


class SettingsSearch(WidgetView, containers.VerticalGroup):
    """Stays above the settings while they scroll."""

    dock = "top"
    padding = Spacing(1, 0, 1, 0)


class SettingsScreen(ToadHosted, PriorityActions, FormModal[None], DismissibleScreen[None]):
    align_horizontal = "right"
    align_vertical = "top"

    def __init__(self) -> None:
        super().__init__()
        self.search = FormInput(placeholder="Search settings")
        self.form = FormView(self.app.saved_settings.state)
        self.search.listen(Input.Changed, self.searched)
        self.listen(events.Mount, self.opened)
        self.listen(events.Unmount, self.closed)

    def compose(self) -> ComposeResult:
        with SettingsPanel():
            with SettingsSearch():
                yield self.search
            yield self.form
        yield ToadFooter()

    def opened(self, event: events.Mount) -> None:
        self.app.saved_settings.open_edits.append(self.form.finish)

    def closed(self, event: events.Unmount) -> None:
        self.app.saved_settings.open_edits.remove(self.form.finish)

    def searched(self, message: Input.Changed) -> None:
        message.stop()
        self.form.filter(message.value)

    def dismiss_control(self) -> None:
        """Leave with every edit sent; the settings are saved once the screen is gone."""
        self.form.finish()
        super().dismiss_control()

    def focus_search(self) -> None:
        self.search.focus()

    def search_wanted(self) -> bool | None:
        return None if self.search.has_focus else True

    def discard(self) -> None:
        self.app.saved_settings.discard()

    MODE_BINDINGS = (
        ModeBinding("ctrl+s", focus_search, "Focus search", mode=EditingMode, available=search_wanted),
        ModeBinding("ctrl+r", discard, "Discard changes", mode=EditingMode),
    )
