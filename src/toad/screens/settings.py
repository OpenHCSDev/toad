"""The settings form: every setting the user may edit, one tab per declared page, searched by label."""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Iterable

from textual import containers, events, getters
from textual.app import ComposeResult
from textual.binding import ModeBinding
from textual.document._editing import EditingMode
from textual.widgets import ContentSwitcher, Input, Tab, Tabs
from toad.widgets.footer import ToadFooter
from textual.geometry import Spacing
from textual.color import Color

from toad.app import ScreenWidth, ToadApp
from toad.forms.editors import SelectEditor
from toad.forms.form_view import FormView, ValueView
from toad.forms.presentation import FormInput, FormModal
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import PriorityActions
from toad.widget_view import FILL, WidgetView
from toad.setting_choices import SchemeName


class SchemeEditor(SelectEditor):
    """A colour scheme's name, picked from the schemes the running app has."""

    shows = (SchemeName,)
    app = getters.app(ToadApp)

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


class SettingsPages(WidgetView, ContentSwitcher):
    """The page of settings whose tab is active; the others stay mounted and hidden."""

    height = FILL


class SettingsScreen(PriorityActions, FormModal[None], DismissibleScreen[None]):
    align_horizontal = "right"
    align_vertical = "top"
    app = getters.app(ToadApp)

    def __init__(self) -> None:
        super().__init__()
        self.search = FormInput(placeholder="Search settings")
        self.pages = FormView.pages(self.app.saved_settings.state)
        for number, form in enumerate(self.pages.values()):
            form.id = f"settings-page-{number}"
        self.listen(Tabs.TabActivated, self.page_chosen)
        self.search.listen(Input.Changed, self.searched)
        self.listen(events.Mount, self.opened)
        self.listen(events.Unmount, self.closed)

    def compose(self) -> ComposeResult:
        with SettingsPanel():
            with SettingsSearch():
                yield self.search
            yield Tabs(*(Tab(page.title, id=form.id) for page, form in self.pages.items()))
            with SettingsPages(initial=next(iter(self.pages.values())).id):
                yield from self.pages.values()
        yield ToadFooter()

    def opened(self, event: events.Mount) -> None:
        self.app.saved_settings.open_edits.append(self.finish)

    def closed(self, event: events.Unmount) -> None:
        self.app.saved_settings.open_edits.remove(self.finish)

    @property
    def values(self) -> ChainMap[str, ValueView]:
        """Every single-value view on every page, by dotted path."""
        return ChainMap(*(form.values for form in self.pages.values()))

    def page_chosen(self, message: Tabs.TabActivated) -> None:
        message.stop()
        self.query_one(SettingsPages).current = message.tab.id

    def finish(self) -> None:
        """Send every edit typed on any page but not left yet."""
        for form in self.pages.values():
            form.finish()

    def searched(self, message: Input.Changed) -> None:
        message.stop()
        for form in self.pages.values():
            form.filter(message.value)

    def dismiss_control(self) -> None:
        """Leave with every edit sent; the settings are saved once the screen is gone."""
        self.finish()
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
