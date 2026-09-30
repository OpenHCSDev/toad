from typing import cast

from textual import on
from textual import getters
from textual.app import ComposeResult

from textual import work
from textual.content import Content
from textual.screen import ModalScreen
from textual import containers
from textual import widgets

import toad
from textual.binding import Binding
from toad.agent_schema import AgentDefinition, OS
from toad.catalog_actions import LaunchAction
from toad.messages import LaunchAgent
from toad.app import ToadApp


class DescriptionContainer(containers.VerticalScroll):
    def allow_focus(self) -> bool:
        """Focus only if it can be scrolled."""
        return self.show_vertical_scrollbar


class AgentModal(ModalScreen[LaunchAgent | None]):
    AUTO_FOCUS = "Select#action-select"

    BINDINGS = [
        Binding("escape", "dismiss(None)", "Dismiss", show=False),
        Binding("space", "launch", "Launch agent", priority=True),
    ]

    app = getters.app(ToadApp)
    action_select = getters.query_one("#action-select", widgets.Select)
    launcher_checkbox = getters.query_one("#launcher-checkbox", widgets.Checkbox)

    def __init__(self, agent: AgentDefinition) -> None:
        self.agent = agent
        super().__init__()

    def compose(self) -> ComposeResult:
        app = self.app
        launcher_set = frozenset(app.settings.launcher.agents.splitlines())
        agent = self.agent
        operations = [command.bind(name)
                      for name, command in agent.commands_for(cast(OS, toad.os)).items()]
        choices = [*operations, LaunchAction(agent)]

        with containers.Vertical(id="container"):
            with DescriptionContainer(id="description-container"):
                yield widgets.Markdown(agent.help, id="description")
            with containers.VerticalGroup():
                for warning in dict.fromkeys(operation.warning(agent.name) for operation in operations):
                    if warning is None:
                        continue
                    yield widgets.Static(
                        Content(warning),
                        classes="acp-warning",
                    )
                with containers.HorizontalGroup():
                    yield widgets.Checkbox(
                        "Show in launcher",
                        value=agent.identity in launcher_set,
                        id="launcher-checkbox",
                    )
                    yield widgets.Select(
                        [(choice.description, choice) for choice in choices],
                        prompt="Actions",
                        allow_blank=True,
                        id="action-select",
                    )
                    yield widgets.Button(
                        "Go", variant="primary", id="run-action", disabled=True
                    )
        yield widgets.Footer()

    def on_mount(self) -> None:
        self.query_one("Footer").styles.animate("opacity", 1.0, duration=500 / 1000)

    @on(widgets.Checkbox.Changed)
    def on_checkbox_changed(self, event: widgets.Checkbox.Changed) -> None:
        launcher_agents = self.app.settings.launcher.agents.splitlines()
        agent_identity = self.agent.identity
        if agent_identity in launcher_agents:
            launcher_agents.remove(agent_identity)
        if event.value:
            launcher_agents.insert(0, agent_identity)
        self.app.settings.launcher.agents = "\n".join(launcher_agents)

    @on(widgets.Select.Changed)
    def on_select_changed(self, event: widgets.Select.Changed) -> None:
        self.query_one("#run-action", widgets.Button).disabled = event.value is widgets.Select.BLANK

    @work
    @on(widgets.Button.Pressed, "#run-action")
    async def on_run_action(self) -> None:
        action = self.action_select.value
        if action is not widgets.Select.BLANK and action.available(self):
            await action.apply(self)

    async def action_launch(self) -> None:
        await LaunchAction(self.agent).apply(self)

    def add_to_launcher(self) -> None:
        if not self.launcher_checkbox.value:
            self.notify(f"{self.agent.name} has been added to your launcher",
                        title="Add agent", severity="information")
            self.launcher_checkbox.value = True
