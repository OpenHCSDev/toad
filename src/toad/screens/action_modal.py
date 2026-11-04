import shutil

from textual.app import ComposeResult
from textual import work
from textual import containers
from textual import getters
from textual.content import Content
from toad.widgets.acting_button import DismissButton
from toad.native_style import FillHeight, FillWidth
from toad.screens.modal import CenteredScreen, DismissibleScreen


from toad.widgets.command_pane import CommandPane
from toad.terminal_execution import Command, TerminalExecution
from toad.agent_schema import AgentDefinition
from toad.catalog_actions import CatalogCommandAction
from toad.core.source_events import CommandComplete
from toad.core_event_carrier import CoreEventReceiver
from metaclass_registry.mro_dispatch import handles
from toad.app_node import ToadNode

UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"


class ActionFrame(FillHeight, containers.VerticalGroup):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (3, 6)
        self.styles.max_height = 48


class ActionButton(FillWidth, DismissButton):
    """Its look is its bases."""


class OkButton(ActionButton):
    """Closes the modal with the command's return code once it has finished."""


class ActionModal(CenteredScreen, CoreEventReceiver, DismissibleScreen[int], ToadNode):
    """Executes an action command."""

    command_pane = getters.query_one(CommandPane)
    ok_button = getters.query_one(OkButton)

    def __init__(
        self,
        action: CatalogCommandAction,
        agent: AgentDefinition,
        command: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.operation = action
        self.agent = agent
        self.command = Command.for_script(command, env=env, cwd=cwd)
        super().__init__()

    def compose(self) -> ComposeResult:
        with ActionFrame():
            yield CommandPane(TerminalExecution(
                self.command
            ))
            with containers.HorizontalGroup():
                yield ActionButton("Cancel")
                yield OkButton("OK", disabled=True)

    def enable_button(self) -> None:
        self.ok_button.loading = False
        self.ok_button.disabled = False
        self.ok_button.focus()

    @handles(CommandComplete)
    def on_command_complete(self, event: CommandComplete) -> None:
        self.operation.command_complete(self, event.return_code)

    def on_mount(self) -> None:
        self.ok_button.loading = True
        self.command_pane.border_title = Content(self.operation.description)
        self.command_pane.focus()
        self.run_command()

    @work()
    async def run_command(self) -> None:
        """Write and execute the command."""
        self.command_pane.anchor()
        execution = self.command_pane.execution
        if self.operation.command.bootstrap_uv and shutil.which("uv") is None:
            # Bootstrap UV if required
            await self.command_pane.write(f"$ {UV_INSTALL}\n")
            bootstrap = TerminalExecution(
                Command.for_script(UV_INSTALL),
                state=execution.state,
            )
            await self.command_pane.execute(bootstrap, final=False)

        await self.command_pane.write(f"$ {execution.command.script}\n")
        await self.command_pane.execute(execution)
        self.app.application.usage.publish(
            "agent-action",
            action=self.operation.name,
            agent=self.agent.identity,
            fail=self.command_pane.return_code != 0,
        )


    def dismiss_control(self) -> None:
        self.dismiss(self.command_pane.return_code)
