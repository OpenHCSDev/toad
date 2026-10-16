"""The settings form: every setting the user may edit, searched by its label."""

from __future__ import annotations

from collections.abc import Iterable

from textual import containers, events, getters
from textual.app import ComposeResult
from textual.binding import CallBinding
from toad.screens.modal import ModalScreen
from textual.widgets import Footer, Input

from toad.app import ToadApp
from toad.forms.editors import SelectEditor
from toad.forms.form_view import FormView
from toad.setting_choices import SchemeName


class SchemeEditor(SelectEditor):
    """A colour scheme's name, picked from the schemes the running app has."""

    shows = (SchemeName,)
    app = getters.app(ToadApp)

    def options(self) -> Iterable[tuple[str, object]]:
        return ((name, name) for name in self.app.colours.schemes)


class SettingsPanel(containers.Vertical):
    """The side of the screen the settings are shown in."""


class SettingsSearch(containers.VerticalGroup):
    """Stays above the settings while they scroll."""


class SettingsScreen(ModalScreen[None]):
    CSS_PATH = "settings.tcss"
    app = getters.app(ToadApp)

    def __init__(self) -> None:
        super().__init__()
        self.search = Input(placeholder="Search settings")
        self.form = FormView(self.app.saved_settings.state)
        self.search.listen(Input.Changed, self.searched)
        self.listen(events.Mount, self.opened)
        self.listen(events.Unmount, self.closed)

    def compose(self) -> ComposeResult:
        with SettingsPanel():
            with SettingsSearch():
                yield self.search
            yield self.form
        yield Footer()

    def opened(self, event: events.Mount) -> None:
        self.app.saved_settings.open_edits.append(self.form.finish)

    def closed(self, event: events.Unmount) -> None:
        self.app.saved_settings.open_edits.remove(self.form.finish)

    def searched(self, message: Input.Changed) -> None:
        message.stop()
        self.form.filter(message.value)

    def close(self) -> None:
        """Leave with every edit sent; the settings are saved once the screen is gone."""
        self.form.finish()
        self.dismiss()

    def focus_search(self) -> None:
        self.search.focus()

    def search_wanted(self) -> bool | None:
        return None if self.search.has_focus else True

    def discard(self) -> None:
        self.app.saved_settings.discard()

    BINDINGS = [
        CallBinding("escape", close, "Dismiss settings"),
        CallBinding("ctrl+s", focus_search, "Focus search", available=search_wanted),
        CallBinding("ctrl+r", discard, "Discard changes"),
    ]
