from __future__ import annotations

from textual import on, containers, getters, lazy
from textual.app import ComposeResult
from textual.screen import ModalScreen, ScreenResultType
from textual.widgets import Input, Footer
from toad.app import ToadApp


class SettingsScreen(ModalScreen):
    BINDINGS = [
        ("escape", "dismiss", "Dismiss settings"),
        ("ctrl+s", "screen.focus('#search')", "Focus search"),
    ]
    CSS_PATH = "settings.tcss"
    app = getters.app(ToadApp)
    search_input = getters.query_one("Input#search", Input)
    AUTO_FOCUS = "Input#search"

    def compose(self) -> ComposeResult:
        with containers.Vertical(id="contents"):
            with containers.VerticalGroup(classes="search-container"):
                yield Input(id="search", placeholder="Search settings")
            with lazy.Reveal(
                containers.VerticalScroll(can_focus=False, id="settings-container")
            ):
                yield from self.app.settings.form()
        yield Footer()

    def filter_settings(self, search_term: str) -> None:
        if search_term:
            search_term = search_term.lower()
            for setting in self.query(".setting"):
                if setting.name:
                    setting.display = search_term in setting.name
            for container in reversed(self.query(".setting-object")):
                container.display = not container.get_child_by_id(
                    "setting-group"
                ).is_empty
        else:
            self.query(".setting").set(display=True)
            self.query(".setting-object").set(display=True)

    @on(Input.Changed, "#search")
    def on_search_input(self, event: Input.Changed) -> None:
        self.filter_settings(event.value)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "focus":
            if not self.is_mounted:
                return None
            return None if self.search_input.has_focus else True
        return True

    async def action_dismiss(self, result: ScreenResultType | None = None) -> None:
        self.query("#search").focus()
        self.call_after_refresh(self.finish_edit, result)

    def finish_edit(self, result: ScreenResultType | None = None) -> None:
        # Textual invokes and awaits callback results. Dismiss schedules stack
        # cleanup; returning its AwaitComplete would wait on this modal's exit.
        self.dismiss(result)
