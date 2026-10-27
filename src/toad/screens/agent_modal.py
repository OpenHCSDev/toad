from textual._callback import invoke

from textual import on
from textual import getters
from textual.app import ComposeResult

from textual import work
from textual.content import Content
from toad.screens.modal import DismissibleScreen
from textual import containers
from textual import widgets
from toad.widgets.footer import ToadFooter

from toad import widget_actions
from toad.widget_actions import HiddenActions, PriorityActions, Launches
from toad.agent_schema import AgentDefinition
from toad.catalog_actions import CatalogCommandAction, LaunchAction
from toad.core.session_requests import LaunchAgent
from toad.app import ToadApp
from toad.preferences import SETTINGS
from toad.platform import host


class DescriptionContainer(containers.VerticalScroll):
    def allow_focus(self) -> bool:
        """Focus only if it can be scrolled."""
        return self.show_vertical_scrollbar


class AgentModal(
    PriorityActions, HiddenActions, Launches, DismissibleScreen[LaunchAgent | None],
    scopes={PriorityActions: (widget_actions.LaunchAction,),
            HiddenActions: (widget_actions.DismissAction,)},
):
    AUTO_FOCUS = "Select#action-select"


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
        operations = [CatalogCommandAction.bind(name, command)
                      for name, command in agent.commands_for(host).items()]
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
        yield ToadFooter()

    def on_mount(self) -> None:
        self.query_one(ToadFooter).styles.animate("opacity", 1.0, duration=500 / 1000)

    @on(widgets.Checkbox.Changed)
    def on_checkbox_changed(self, event: widgets.Checkbox.Changed) -> None:
        launcher_agents = self.app.settings.launcher.agents.splitlines()
        agent_identity = self.agent.identity
        if agent_identity in launcher_agents:
            launcher_agents.remove(agent_identity)
        if event.value:
            launcher_agents.insert(0, agent_identity)
        self.app.saved_settings.set(SETTINGS.launcher.agents, "\n".join(launcher_agents))

    @on(widgets.Select.Changed)
    def on_select_changed(self, event: widgets.Select.Changed) -> None:
        self.query_one("#run-action", widgets.Button).disabled = event.value is widgets.Select.NULL

    @on(widgets.Button.Pressed, "#run-action")
    @work
    async def on_run_action(self) -> None:
        action = self.action_select.value
        if action is not widgets.Select.NULL and action.available(self):
            await invoke(action.apply, self)

    async def launch(self) -> None:
        await LaunchAction(self.agent).apply(self)

    def add_to_launcher(self) -> None:
        if not self.launcher_checkbox.value:
            self.notify(f"{self.agent.name} has been added to your launcher",
                        title="Add agent", severity="information")
            self.launcher_checkbox.value = True
