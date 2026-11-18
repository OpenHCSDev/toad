"""The settings form: every setting the user may edit, one tab per declared page, searched by label."""

from __future__ import annotations

from collections import ChainMap
from collections.abc import Iterable

from formbridge.key_declarations import TextEntryMode
from textual.css.scalar import Scalar, Unit
from textual import containers, events
from textual.app import ComposeResult

from textual.view import (
    FILL,
    WidgetView,
)
from textual.widgets import ContentSwitcher, Input, Tab, Tabs
from toad.widgets.footer import ToadFooter
from textual.geometry import Spacing
from textual.color import Color

from toad.screen_width import ScreenWidth
from toad.form_family import SchemeChoosing
from toad.settings_editing import SettingsEditing
from toad.forms.editors import SelectEditor
from toad.forms.form_view import FormView, ValueView
from toad.forms.presentation import FormInput, FormModal
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction, PriorityActions, WidgetAction
from toad.setting_choices import SchemeName
from toad.app_node import ToadNode


class SchemeEditor(SchemeChoosing, SelectEditor, ToadNode, shows=(SchemeName,)):
    """A colour scheme's name, picked from the schemes the running app has (pywal's included)."""

    def scheme_names(self) -> Iterable[str]:
        return self.app.colours.schemes


class SettingsPanel(WidgetView, containers.Vertical):
    """The side of the screen the settings are shown in."""

    height = None
    padding = Spacing(0, 1, 0, 1)
    paint_background = Color(0, 0, 0, 0.1)

    @property
    def width(self):
        percent = ScreenWidth(self.screen.horizontal_breakpoint).side_panel_percent
        return None if percent is None else Scalar(percent, Unit.PERCENT, Unit.WIDTH)


class SettingsSearch(WidgetView, containers.VerticalGroup):
    """Stays above the settings while they scroll."""

    dock = "top"
    padding = Spacing(1, 0, 1, 0)


class SettingsPages(WidgetView, ContentSwitcher):
    """The page of settings whose tab is active; the others stay mounted and hidden."""

    height = FILL


class SettingsAction(WidgetAction, affix="Action"):
    """What the settings screen does on its own keys."""


class FocusSearchAction(SettingsAction):
    """Move to the settings search; hidden while the search already has focus."""

    title = "Focus search"
    keys = {TextEntryMode: ("ctrl+s",)}
    show = True

    def available(self, context: SettingsScreen) -> bool:
        return not context.search.has_focus

    def apply(self, context: SettingsScreen) -> None:
        context.search.focus()


class DiscardAction(SettingsAction):
    """Throw away the edits not yet saved."""

    title = "Discard changes"
    keys = {TextEntryMode: ("ctrl+r",)}
    show = True

    def apply(self, context: SettingsScreen) -> None:
        context.discard()


class SettingsScreen(SettingsEditing, PriorityActions, FormModal[None], DismissibleScreen[None], ToadNode,
                     actions=(SettingsAction,), scopes={PriorityActions: (DismissAction,)}):
    align_horizontal = "right"
    align_vertical = "top"

    def __init__(self) -> None:
        super().__init__()
        self.search = FormInput(placeholder="Search settings")
        self.build_pages()
        # The page switcher keeps every page mounted (hidden while another is shown), so
        # every page is shown, and built, as the screen composes.
        for number, page in enumerate(self.listed):
            self.page(page).id = f"settings-page-{number}"
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

    @property
    def edited_settings(self):
        return self.app.saved_settings

    @classmethod
    def form_type(cls):
        return FormView

    def opened(self, event: events.Mount) -> None:
        self.start_editing()

    def closed(self, event: events.Unmount) -> None:
        self.stop_editing()

    @property
    def values(self) -> ChainMap[str, ValueView]:
        """Every single-value view on every page, by dotted path."""
        return ChainMap(*(form.values for form in self.pages.values()))

    def page_chosen(self, message: Tabs.TabActivated) -> None:
        message.stop()
        self.query_one(SettingsPages).current = message.tab.id

    def searched(self, message: Input.Changed) -> None:
        message.stop()
        self.filter_pages(message.value)

    def dismiss_control(self) -> None:
        """Leave with every edit sent; the settings are saved once the screen is gone."""
        self.finish()
        super().dismiss_control()

