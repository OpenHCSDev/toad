from __future__ import annotations

from textual import on, containers, getters, lazy
from textual.app import ComposeResult
from textual.screen import ModalScreen, ScreenResultType
from textual.widgets import Input, Footer
from textual.content import Content
from agent_comms.mro_dispatch import handles
from toad.core.projection import MroProjection
from toad.settings import (
    BoundSetting, Group, SettingsGroup, BooleanSetting, StringSetting,
    TextSetting, PathSetting, IntegerSetting, NumberSetting, ChoiceSetting,
)
from toad.setting_widgets import InputEditor, TextEditor, BooleanEditor, ChoiceEditor
from toad.app import ToadApp


class SettingsScreen(MroProjection, ModalScreen):
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
                yield from self.form(self.app.settings)
        yield Footer()

    def form(self, group: SettingsGroup, title: str = ""):
        for node in group.nodes():
            if node.editable:
                yield self.dispatch_sync(node, group, title)

    @handles(Group)
    def group_form(self, node, group, title):
        from textual.widgets import Static

        return containers.VerticalGroup(
            containers.VerticalGroup(
                Static(node.title, classes="title"),
                Static(node.help, classes="help"), classes="heading",
            ),
            containers.VerticalGroup(
                *self.form(node.__get__(group), node.title),
                id="setting-group", classes="setting-group",
            ), classes="setting-object",
        )

    def description(self, kind):
        return Content.assemble(
            Content.from_markup(kind.help),
            (f"\ndefault: {kind.display(kind.default)}", "$text-secondary"),
        )

    def row(self, bound, editor, title, description):
        from textual.widgets import Static

        return containers.VerticalGroup(
            Static(bound.kind.title, classes="title"),
            Static(description, classes="help"), editor,
            classes="setting", name=f"{title.lower()} {bound.kind.title.lower()}",
        )

    def leaf(self, kind, group, title, editor):
        bound = BoundSetting(kind, group)
        return self.row(bound, editor(bound), title, self.description(kind))

    @handles(BooleanSetting)
    def boolean_form(self, kind, group, title):
        return self.leaf(kind, group, title, BooleanEditor)

    @handles(StringSetting, PathSetting)
    def input_form(self, kind, group, title):
        return self.leaf(kind, group, title, InputEditor)

    @handles(TextSetting)
    def text_form(self, kind, group, title):
        bound = BoundSetting(kind, group)
        return self.row(bound, TextEditor(bound), title, Content.from_markup(kind.help))

    @handles(IntegerSetting)
    def integer_form(self, kind, group, title):
        bound = BoundSetting(kind, group)
        return self.row(bound, InputEditor(bound, type="integer"),
                        title, self.description(kind))

    @handles(NumberSetting)
    def number_form(self, kind, group, title):
        bound = BoundSetting(kind, group)
        return self.row(bound, InputEditor(bound, type="number"),
                        title, self.description(kind))

    @handles(ChoiceSetting)
    def choice_form(self, kind, group, title):
        return self.leaf(kind, group, title, ChoiceEditor)

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
