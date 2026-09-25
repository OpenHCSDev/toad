"""Visible projection of inputs without a confirmed native start."""

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class InputDeliveryBar(HorizontalGroup):
    DEFAULT_CSS = """
    InputDeliveryBar { height: 1; padding: 0 1; }
    InputDeliveryBar Static { width: 1fr; color: $warning; }
    InputDeliveryBar Button { height: 1; min-width: 9; border: none; padding: 0 1; }
    """
    inputs: var[list[dict]] = var(list)

    class Inspect(Message):
        pass

    def compose(self) -> ComposeResult:
        yield Static(markup=False, id="delivery-summary")
        yield Button("Inspect", id="delivery-inspect")

    def watch_inputs(self) -> None:
        self.display = bool(self.inputs)
        if self.is_attached:
            self.query_one("#delivery-summary", Static).update(
                f"Delivery · {len(self.inputs)} input(s) awaiting confirmed start"
            )

    def on_mount(self) -> None:
        self.watch_inputs()

    @on(Button.Pressed, "#delivery-inspect")
    def inspect(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.Inspect())


class InputDeliveryDetails(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    InputDeliveryDetails { align: center middle; background: $background 40%; }
    InputDeliveryDetails > Vertical {
        width: 90%; height: 85%; padding: 1;
        border: solid $primary; background: $surface;
    }
    InputDeliveryDetails VerticalScroll { height: 1fr; }
    InputDeliveryDetails Static { height: auto; margin-bottom: 1; }
    InputDeliveryDetails HorizontalGroup { height: auto; }
    """
    inputs: var[list[dict]] = var(list)

    def __init__(self, *, log_path: Path | None):
        super().__init__()
        self.log_path = log_path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Unresolved delivery", markup=False)
            yield Static(
                "These inputs have no confirmed native start. They may have reached the agent. "
                "They are not automatically retried.", markup=False,
            )
            with VerticalScroll():
                yield Static(markup=False, id="delivery-records")
            with HorizontalGroup():
                if self.log_path is not None:
                    yield Button("Open ACP log", id="delivery-log")
                yield Button("Close (Esc)", id="delivery-close")

    def watch_inputs(self) -> None:
        if self.is_attached:
            self.query_one("#delivery-records", Static).update(
                "\n\n".join(
                    f"Sequence: {row['sequence'] if row['sequence'] is not None else 'direct input'}"
                    f" · Target: {row['target']}\nInput: {row['inputId']}\n{row['text']}"
                    for row in self.inputs
                ) or "No unresolved inputs."
            )

    def on_mount(self) -> None:
        self.watch_inputs()

    @on(Button.Pressed, "#delivery-close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#delivery-log")
    async def open_log(self) -> None:
        if self.log_path is not None:
            await self.app.open_file_preview(self.log_path)
