from textual._callback import invoke

from textual import on
from textual import getters
from textual.app import ComposeResult

from textual import work
from textual.content import Content
from textual.css.native import NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.widgets._markdown import MarkdownH1
from ui_theme.scheme import AccentColour, PrimaryColour, SuccessColour
from toad.widgets.acting_button import ConfirmButton, Confirms
from toad.native_style import (
    AutoHeight,
    FillWidth,
    NoMargin,
    RightMargin,
    SidePadding,
    TransparentBackground,
)
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalFrame
from textual import containers
from textual import widgets
from textual.widgets._footer import FooterKeyComponent
from toad.widgets.footer import ToadFooter, ToadFooterKey
from toad.widgets.checkbox import Checkbox

from toad import widget_actions
from toad.widget_actions import HiddenActions, PriorityActions, Launches
from toad.agent_schema import AgentDefinition
from toad.catalog_actions import CatalogCommandAction, LaunchAction
from toad.core.session_requests import LaunchAgent
from toad.preferences import SETTINGS
from toad.platform import host
from toad.app_node import ToadNode


class DescriptionContainer(
    TransparentBackground,
    AutoHeight,
    containers.VerticalScroll,
):
    """The agent's help; tinted while it has focus."""

    focus_theme = (NativeDeclaration.of(Styles.background, Variable(PrimaryColour.name), Percent(7)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 0, 1, 1)
        self.styles.max_height = 20

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *((), self.focus_theme)[self.has_focus])

    def watch_has_focus(self, has_focus: bool) -> None:
        super().watch_has_focus(has_focus)
        self.app.update_styles(self)

    def allow_focus(self) -> bool:
        """Focus only if it can be scrolled."""
        return self.show_vertical_scrollbar


class AgentHelpHeading(MarkdownH1):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (1, 1, 1, 0)


class AgentHelp(SidePadding, widgets.Markdown):
    BLOCKS = widgets.Markdown.BLOCKS | {f"h{AgentHelpHeading.LEVEL}": AgentHelpHeading}



class AcpWarning(SidePadding, widgets.Static):
    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(SuccessColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 0, 1, 1)


class LauncherCheckbox(NoMargin, Checkbox):
    """Its look is its bases."""


class ActionSelect(RightMargin, FillWidth, widgets.Select):
    """Its look is its bases."""


class RunAction(ConfirmButton):
    """Runs the chosen action."""


class AgentModalFooterKey(ToadFooterKey):
    """Keys are accented over every state the footer paints them in."""

    accent_components = {
        FooterKeyComponent.KEY: (NativeDeclaration.of(Styles.color, Variable(AccentColour.name)),),
    }

    def native_component_declarations(self, component: FooterKeyComponent) -> tuple[NativeDeclaration, ...]:
        return (*super().native_component_declarations(component), *self.accent_components.get(component, ()))


class AgentModalFooter(ToadFooter, setting=ToadFooter.visibility_setting):
    """Fades in once the modal has mounted."""

    key_type = AgentModalFooterKey

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.opacity = 0.0


class AgentModal(
    Confirms, CenteredScreen, PriorityActions, HiddenActions, Launches, DismissibleScreen[LaunchAgent | None],
    ToadNode,
    scopes={PriorityActions: (widget_actions.LaunchAction,),
            HiddenActions: (widget_actions.DismissAction,)},
):
    AUTO_FOCUS = "ActionSelect"

    action_select = getters.query_one(ActionSelect)
    launcher_checkbox = getters.query_one(LauncherCheckbox)
    run_button = getters.query_one(RunAction)

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

        with ModalFrame():
            with DescriptionContainer():
                yield AgentHelp(agent.help)
            with containers.VerticalGroup():
                for warning in dict.fromkeys(operation.warning(agent.name) for operation in operations):
                    if warning is None:
                        continue
                    yield AcpWarning(Content(warning))
                with containers.HorizontalGroup():
                    yield LauncherCheckbox(
                        "Show in launcher",
                        value=agent.identity in launcher_set,
                    )
                    yield ActionSelect(
                        [(choice.description, choice) for choice in choices],
                        prompt="Actions",
                        allow_blank=True,
                    )
                    yield RunAction("Go", variant="primary", disabled=True)
        yield AgentModalFooter()

    def on_mount(self) -> None:
        self.query_one(AgentModalFooter).styles.animate("opacity", 1.0, duration=500 / 1000)

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
        self.run_button.disabled = event.value is widgets.Select.NULL

    async def confirm(self) -> None:
        self.run_selected_action()

    @work
    async def run_selected_action(self) -> None:
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
