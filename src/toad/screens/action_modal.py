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

UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"


class ActionModal(ModalScreen):
    """Executes an action command."""

    CSS_PATH = "store.tcss"

    command_pane = getters.query_one(CommandPane)
    ok_button = getters.query_one("#ok", widgets.Button)

    app = getters.app(ToadApp)

    BINDINGS = [("escape", "dismiss_modal", "Dismiss")]

    def __init__(
        self,
        action: str,
        agent: str,
        title: str,
        command: str,
        *,
        bootstrap_uv: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._action = action
        self._agent = agent
        self._title = title
        self._command = command
        self._bootstrap_uv = bootstrap_uv
        self._env = env
        self._cwd = cwd
        super().__init__(name=name, id=id, classes=classes)

    def get_loading_widget(self) -> Widget:
        return widgets.LoadingIndicator()

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(id="container"):
            yield CommandPane()
            with containers.HorizontalGroup(id="action-buttons"):
                yield widgets.Button("Cancel", id="cancel")
                yield widgets.Button("OK", id="ok", disabled=True)

    def enable_button(self) -> None:
        self.ok_button.loading = False
        self.ok_button.disabled = False
        self.ok_button.focus()

    @on(CommandPane.CommandComplete)
    def on_command_complete(self, event: CommandPane.CommandComplete) -> None:
        if self._action == "login" and event.return_code == 0:
            self.dismiss(0)
        else:
            self.enable_button()

    def on_mount(self) -> None:
        self.ok_button.loading = True
        self.command_pane.border_title = Content(self._title)
        self.command_pane.focus()
        self.run_command()

    @work()
    async def run_command(self) -> None:
        """Write and execute the command."""
        self.command_pane.anchor()
        if self._bootstrap_uv and shutil.which("uv") is None:
            # Bootstrap UV if required
            await self.command_pane.write(f"$ {UV_INSTALL}\n")
            await self.command_pane.execute(UV_INSTALL, final=False)

        await self.command_pane.write(f"$ {self._command}\n")
        action_task = self.command_pane.execute(
            self._command, env=self._env, cwd=self._cwd
        )
        await action_task
        self.app.capture_event(
            "agent-action",
            action=self._action,
            agent=self._agent,
            fail=self.command_pane.return_code != 0,
        )

    @on(widgets.Button.Pressed)
    async def on_button_pressed(self, event: widgets.Button.Pressed) -> None:
        if event.button.id == "cancel":
            await self.command_pane.cancel_command()
            self.dismiss(None)
        else:
            self.action_dismiss_modal()

    def action_dismiss_modal(self) -> None:
        self.dismiss(self.command_pane.return_code)
