"""Server-owned current delivery state and dismissible historical notices."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from textual import events, on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import var
from textual.screen import ModalScreen
from textual.widgets import Button, Static


def empty_delivery() -> dict:
    return {
        "inputs": [],
        "historicalCount": 0,
        "dismissedHistoricalCount": 0,
        "historicalInputs": [],
    }


class DeliveryInspect(Static, can_focus=True):
    """An inline text action without a button's border or minimum height."""

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("enter,space", "inspect", "Inspect delivery")
    ]
    DEFAULT_CSS = """
    DeliveryInspect {
        width: auto; height: 1; margin-left: 1;
        color: $text-accent; text-style: underline; pointer: pointer;
    }
    DeliveryInspect:hover, DeliveryInspect:focus { text-style: bold reverse; }
    """

    def action_inspect(self) -> None:
        if not self.disabled:
            self.post_message(InputDeliveryBar.Inspect())

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_inspect()


class DeliveryHistoryAction(DeliveryInspect):
    """Keyboard and pointer action for historical notices only."""

    class Activated(Message):
        def __init__(self, action: DeliveryHistoryAction):
            self.action = action
            super().__init__()

    def action_inspect(self) -> None:
        if not self.disabled:
            self.post_message(self.Activated(self))


class InputDeliveryBar(HorizontalGroup):
    DEFAULT_CSS = """
    InputDeliveryBar { height: auto; padding: 0 1; }
    InputDeliveryBar #delivery-summary { width: auto; height: auto; color: $warning; }
    InputDeliveryBar #delivery-history-summary { width: 1fr; height: auto; color: $text-muted; }
    InputDeliveryBar #delivery-error { width: 1fr; height: auto; color: $warning; }
    """
    delivery: var[dict] = var(empty_delivery)
    error: var[str] = var("")

    class Inspect(Message):
        pass

    def compose(self) -> ComposeResult:
        yield Static(markup=False, id="delivery-summary")
        yield Static(markup=False, id="delivery-history-summary")
        yield Static(markup=False, id="delivery-error")
        yield DeliveryInspect("Inspect", markup=False, id="delivery-inspect")

    def watch_delivery(self) -> None:
        self._refresh_summary()

    def watch_error(self) -> None:
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        current = len(self.delivery["inputs"])
        history = self.delivery["historicalCount"]
        self.display = bool(current or history or self.error)
        if self.is_attached:
            summary = self.query_one("#delivery-summary", Static)
            summary.display = bool(current)
            summary.update(f"Delivery · {current} unconfirmed")
            historical = self.query_one("#delivery-history-summary", Static)
            historical.display = bool(history)
            historical.update(f"{' · ' if current else ''}{history} historical notices")
            error = self.query_one("#delivery-error", Static)
            error.display = bool(self.error)
            error.update(self.error)

    def on_mount(self) -> None:
        self._refresh_summary()


class InputDeliveryDetails(ModalScreen[None]):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("escape", "close", "Close")]
    DEFAULT_CSS = """
    InputDeliveryDetails { align: center middle; background: $background 40%; }
    InputDeliveryDetails > Vertical {
        width: 90%; height: 85%; padding: 1;
        border: solid $primary; background: $surface;
    }
    InputDeliveryDetails VerticalScroll { height: 1fr; }
    InputDeliveryDetails Static { height: auto; margin-bottom: 1; }
    InputDeliveryDetails HorizontalGroup { height: auto; }
    InputDeliveryDetails #delivery-error { color: $warning; }
    InputDeliveryDetails #delivery-historical-summary { color: $text-muted; }
    InputDeliveryDetails DeliveryHistoryAction { height: 1; }
    """
    delivery: var[dict] = var(empty_delivery)
    error: var[str] = var("")

    def __init__(
        self,
        *,
        log_path: Path | None,
        load_history: Callable[[], Awaitable[list[dict]]],
        dismiss_history: Callable[[], Awaitable[None]],
    ):
        super().__init__()
        self.log_path = log_path
        self._load_history = load_history
        self._dismiss_history = dismiss_history
        self._historical_inputs: list[dict] | None = None
        self._busy = False

    @property
    def inputs(self) -> list[dict]:
        return self.delivery["inputs"]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Input delivery", markup=False)
            yield Static(markup=False, id="delivery-error")
            with VerticalScroll():
                yield Static(
                    "Current inputs have no confirmed native start. They may have reached the agent. "
                    "They are not automatically retried.",
                    markup=False,
                )
                yield Static(markup=False, id="delivery-records")
                yield Static(markup=False, id="delivery-historical-summary")
                yield Static(
                    "Historical notices lack receipts from before delivery tracking. "
                    "They are not proof that an input is unread. Clearing these notices only hides "
                    "them; it does not confirm delivery, mark messages read, or retry inputs.",
                    markup=False,
                    id="delivery-history-explanation",
                )
                yield DeliveryHistoryAction(
                    "Load historical notices",
                    markup=False,
                    id="delivery-load-history",
                )
                yield DeliveryHistoryAction(
                    "Clear historical notices",
                    markup=False,
                    id="delivery-clear-history",
                )
                yield Static(markup=False, id="delivery-historical-records")
            with HorizontalGroup():
                if self.log_path is not None:
                    yield Button("Open ACP log", id="delivery-log")
                yield Button("Close (Esc)", id="delivery-close")

    @staticmethod
    def _records(inputs: list[dict]) -> str:
        return "\n\n".join(
            f"Sequence: {row['sequence'] if row['sequence'] is not None else 'direct input'}"
            f" · Target: {row['target']}\nInput: {row['inputId']}\n{row['text']}"
            + ("\nNotice cleared." if row.get("noticeDismissed") else "")
            for row in inputs
        )

    def watch_delivery(self, old: dict, new: dict) -> None:
        if any(
            old[key] != new[key]
            for key in ("historicalCount", "dismissedHistoricalCount")
        ):
            self._historical_inputs = None
        self._refresh_records()

    def watch_error(self) -> None:
        if self.is_attached:
            error = self.query_one("#delivery-error", Static)
            error.display = bool(self.error)
            error.update(self.error)

    def _refresh_records(self) -> None:
        if not self.is_attached:
            return
        self.query_one("#delivery-records", Static).update(
            self._records(self.inputs) or "No current unconfirmed inputs."
        )
        count = self.delivery["historicalCount"]
        dismissed = self.delivery["dismissedHistoricalCount"]
        self.query_one("#delivery-historical-summary", Static).update(
            f"{count} historical notices · {dismissed} cleared"
        )
        self.query_one("#delivery-history-explanation").display = bool(
            count or dismissed
        )
        load = self.query_one("#delivery-load-history", DeliveryHistoryAction)
        load.display = bool(count or dismissed) and self._historical_inputs is None
        load.disabled = self._busy
        clear = self.query_one("#delivery-clear-history", DeliveryHistoryAction)
        clear.display = bool(count)
        clear.disabled = self._busy
        self.query_one("#delivery-historical-records", Static).update(
            self._records(self._historical_inputs or [])
        )

    def on_mount(self) -> None:
        self._refresh_records()
        self.watch_error()

    @on(DeliveryHistoryAction.Activated)
    async def historical_action(self, event: DeliveryHistoryAction.Activated) -> None:
        event.stop()
        if self._busy:
            return
        self._busy = True
        self.error = ""
        self._refresh_records()
        try:
            if event.action.id == "delivery-load-history":
                self._historical_inputs = await self._load_history()
            else:
                await self._dismiss_history()
                self._historical_inputs = None
        except (OSError, ValueError, RuntimeError, TimeoutError, KeyError) as error:
            self.error = f"Delivery history unavailable: {error}"
        finally:
            self._busy = False
            self._refresh_records()

    @on(Button.Pressed, "#delivery-close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#delivery-log")
    async def open_log(self) -> None:
        if self.log_path is not None:
            await self.app.open_file_preview(self.log_path)
