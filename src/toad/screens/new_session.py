"""Choose a new session's project before the lifecycle creates any agent."""
from pathlib import Path

from textual import containers, on, widgets
from textual.app import ComposeResult
from toad.screens.modal import ModalScreen

from toad.widgets.directory_input import DirectoryInput


class NewSessionModal(ModalScreen[Path | None]):
    AUTO_FOCUS = "DirectoryInput"
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]
    DEFAULT_CSS = """
    NewSessionModal { align: center middle; background: $background 60%; }
    NewSessionModal > VerticalGroup {
        width: 72; max-width: 100%; padding: 1 2;
        border: round $primary; background: $background;
    }
    NewSessionModal .error { color: $error; height: auto; }
    NewSessionModal HorizontalGroup { align-horizontal: right; height: auto; }
    """

    def __init__(self, project: Path) -> None:
        super().__init__()
        self.project = project

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup():
            yield widgets.Label("New agent session")
            yield widgets.Label("Project directory")
            yield DirectoryInput(value=str(self.project))
            yield widgets.Static("", classes="error", markup=False)
            with containers.HorizontalGroup():
                yield widgets.Button("Cancel", id="cancel")
                yield widgets.Button("Create", id="create", variant="primary")

    @on(widgets.Button.Pressed, "#cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(widgets.Button.Pressed, "#create")
    @on(widgets.Input.Submitted)
    async def create(self) -> None:
        value = self.query_one(DirectoryInput).value.strip()
        if not value:
            self.query_one(".error", widgets.Static).update("Choose a project directory.")
            return

        def project() -> Path:
            path = Path(value).expanduser().resolve(strict=True)
            if not path.is_dir():
                raise ValueError("The project must be a directory.")
            return path

        try:
            selected = await self.app.preparation.run_thread(project)
        except (OSError, ValueError) as error:
            self.query_one(".error", widgets.Static).update(str(error))
            return
        self.dismiss(selected)
