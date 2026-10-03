import shutil

from textual.app import ComposeResult
from textual import on, work
from textual import containers
from textual import getters
from textual.content import Content
from textual.screen import ModalScreen
from textual import widgets
from textual.widget import Widget

from toad.app import ToadApp
from toad.widgets.command_pane import CommandPane
from toad.terminal_execution import Command, TerminalExecution
from toad.agent_schema import AgentDefinition
from toad.catalog_actions import CatalogCommandAction
from toad.core.source_events import CommandComplete
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from agent_comms.mro_dispatch import handles

UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"


class ActionModal(CoreEventReceiver, ModalScreen):
    """Executes an action command."""

    CSS_PATH = "store.tcss"

    command_pane = getters.query_one(CommandPane)
    ok_button = getters.query_one("#ok", widgets.Button)

    app = getters.app(ToadApp)

    BINDINGS = [("escape", "dismiss_modal", "Dismiss")]

    def __init__(
        self,
        action: CatalogCommandAction,
        agent: AgentDefinition,
        command: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.operation = action
        self.agent = agent
        self._command = command
        self._env = env
        self._cwd = cwd
        super().__init__(name=name, id=id, classes=classes)

    def get_loading_widget(self) -> Widget:
        return widgets.LoadingIndicator()

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(id="container"):
            yield CommandPane(TerminalExecution(
                Command.for_script(self._command, env=self._env, cwd=self._cwd)
            ))
            with containers.HorizontalGroup(id="action-buttons"):
                yield widgets.Button("Cancel", id="cancel")
                yield widgets.Button("OK", id="ok", disabled=True)

    def enable_button(self) -> None:
        self.ok_button.loading = False
        self.ok_button.disabled = False
        self.ok_button.focus()

    @handles(CommandComplete)
    def on_command_complete(self, event: CoreEventMessage) -> None:
        self.operation.command_complete(self, event.event.return_code)

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

        await self.command_pane.write(f"$ {self._command}\n")
        await self.command_pane.execute(execution)
        self.app.application.usage.publish(
            "agent-action",
            action=self.operation.name,
            agent=self.agent.identity,
            fail=self.command_pane.return_code != 0,
        )

    @on(widgets.Button.Pressed, "#cancel")
    async def cancel_command(self, event: widgets.Button.Pressed) -> None:
        await self.command_pane.cancel_command()
        self.dismiss(None)

    @on(widgets.Button.Pressed, "#ok")
    def action_dismiss_modal(self) -> None:
        self.dismiss(self.command_pane.return_code)
