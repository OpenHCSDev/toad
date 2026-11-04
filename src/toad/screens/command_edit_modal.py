from textual.widget import Widget
from textual.app import ComposeResult
from toad.widgets.acting_button import ConfirmButton, Confirms, DismissButton
from toad.native_style import FillWidth, PrimaryText
from toad.screens.modal import CenteredScreen, DismissibleScreen, ModalFrame
from toad.widget_actions import WidgetAction
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

    async def apply(self, context: CommandEditModal) -> None:
        context.app.copy_to_clipboard(context.text_area.text)
        context.notify("Command copied to clipboard", title=self.title)


class CommandFrame(ModalFrame):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 1, 0, 1)
        self.styles.margin = (3, 6)
        self.styles.max_width = 80


class InstructionText(PrimaryText, Widget):

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 1, 1, 1)


class CommandTitle(InstructionText, widgets.Label):
    """The dialog's centred title."""


class CommandHelp(InstructionText, widgets.Static):
    """What the dialog will do with the command."""


class CommandText(widgets.TextArea):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 6


class CommandButtons(FillWidth, containers.HorizontalGroup):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 1, 0, 1)
        self.styles.align = ("right", "top")


class CommandEditModal(Confirms, CenteredScreen, DismissibleScreen[str | None], actions=(CopyCommandAction,)):
    AUTO_FOCUS = "Button"

    text_area = getters.query_one(CommandText)

    def __init__(
        self,
        command: str,
    ):
        self.command = command
        super().__init__()

    def compose(self) -> ComposeResult:
        with CommandFrame():
            with containers.Center():
                yield CommandTitle("[b]Run command")
            yield CommandHelp("Toad will run the following command (edit if you need to).")
            yield CommandText(
                self.command,
                language="bash",
                highlight_cursor_line=False,
                soft_wrap=False,
            )
            with CommandButtons():
                yield ConfirmButton("OK", variant="primary")
                yield DismissButton("Cancel")
        yield ToadFooter()

    async def confirm(self) -> None:
        self.dismiss(self.text_area.text)
