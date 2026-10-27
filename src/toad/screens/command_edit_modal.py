from textual import on
from textual.app import ComposeResult
from toad.screens.modal import DismissibleScreen
from toad.widget_actions import DismissAction, WidgetAction
from textual.document._editing import EditingMode
from textual import widgets
from toad.widgets.footer import ToadFooter
from textual import containers
from textual import getters


class CopyCommandAction(WidgetAction):
    """Copy the complete edited command to the clipboard."""
    title = "Copy command"
    keys = {EditingMode: ("ctrl+c",)}
    show = True

    async def apply(self, context):
        context.app.copy_to_clipboard(context.text_area.text)
        context.notify("Command copied to clipboard", title=self.title)


class CommandEditModal(DismissibleScreen[str | None], actions=(CopyCommandAction,)):
    AUTO_FOCUS = "Button"

    text_area = getters.query_one(widgets.TextArea)

    def __init__(
        self,
        command: str,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ):
        self.command = command
        super().__init__(name=name, id=id, classes=classes)

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(id="container"):
            with containers.Center():
                yield widgets.Label(
                    "[b]Run command",
                    classes="instructions",
                )
            yield widgets.Static(
                "Toad will run the following command (edit if you need to).",
                classes="instructions",
            )
            yield widgets.TextArea(
                self.command,
                language="bash",
                highlight_cursor_line=False,
                soft_wrap=False,
            )
            with containers.HorizontalGroup(id="button-container"):
                yield widgets.Button("OK", variant="primary", id="ok")
                yield widgets.Button("Cancel", id="cancel", action=f"screen.{DismissAction.binding_name()}")
        yield ToadFooter()

    @on(widgets.Button.Pressed, "#ok")
    def on_ok_pressed(self, event: widgets.Button.Pressed) -> None:
        self.dismiss(self.text_area.text)
