"""The settings form: every setting the user may edit, searched by its label."""

from __future__ import annotations

from collections.abc import Iterable

from textual import containers, events, getters
from textual.app import ComposeResult
from textual.binding import CallBinding
from textual.screen import ModalScreen
from textual.widgets import Footer, Input
from textual.css.scalar import Scalar, Unit
from textual.geometry import Spacing
from textual.color import Color

from toad.app import ToadApp
from toad.forms.editors import SelectEditor
from toad.forms.form_view import FormView
from toad.forms.presentation import FormInput, FormModal, FormPart
from toad.setting_choices import SchemeName


class SchemeEditor(SelectEditor):
    """A colour scheme's name, picked from the schemes the running app has."""

    shows = (SchemeName,)
    app = getters.app(ToadApp)

    def options(self) -> Iterable[tuple[str, object]]:
        return ((name, name) for name in self.app.colours.schemes)


class SettingsPanel(FormPart, containers.Vertical):
    """The side of the screen the settings are shown in."""

    height = None
    padding = Spacing(0, 1, 0, 1)
    paint_background = Color(0, 0, 0, 0.1)

    @property
    def width(self):
        return None if self.screen.has_class("-narrow") else Scalar(50, Unit.PERCENT, Unit.WIDTH)


class SettingsSearch(FormPart, containers.VerticalGroup):
    """Stays above the settings while they scroll."""

    dock = "top"
    padding = Spacing(1, 0, 1, 0)


class SettingsScreen(FormModal, ModalScreen[None]):
    align_horizontal = "right"
    align_vertical = "top"
    app = getters.app(ToadApp)

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
