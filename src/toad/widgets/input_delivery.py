"""Server-owned current delivery state and dismissible historical notices."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import events, on
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import var
from toad.screens.modal import ModalScreen
from textual.widgets import Button, Static
from textual._activation import PrimaryActivation

from agent_comms.input_attempt import HistoricalInput
from agent_comms.ui_model.delivery import DeliveryView
from toad.project_link import AcpLogLink
from toad.widgets.selection import ChangingText, InlineSelection
from rich.style import Style as RichStyle


class DetailAction(InlineSelection, PrimaryActivation, Static, can_focus=True):
    """An inline detail action owns keyboard, pointer and activation behavior."""

    highlighted_text_style = RichStyle(bold=True, reverse=True)

    class Activated(Message):
        def __init__(self, control: DetailAction):
            self._control = control
            super().__init__()

        @property
        def control(self) -> DetailAction:
            return self._control

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("enter,space", "activate", "Activate")
    ]
    DEFAULT_CSS = """
    DetailAction {
        width: auto; height: 1; margin-left: 1;
        color: $text-accent; text-style: underline; pointer: pointer;
    }
    """

    @property
    def primary_activation(self):
        return self.action_activate

    def action_activate(self) -> None:
        if not self.disabled:
            self.post_message(self.Activated(self))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.action_activate()


class InputDeliveryBar(HorizontalGroup):
    DEFAULT_CSS = """
    InputDeliveryBar { height: auto; padding: 0 1; }
    InputDeliveryBar #delivery-summary { width: auto; height: auto; color: $warning; }
    InputDeliveryBar #delivery-history-summary { width: 1fr; height: auto; color: $text-muted; }
    InputDeliveryBar #delivery-error { width: 1fr; height: auto; color: $warning; }
    """
    delivery: var[DeliveryView] = var(DeliveryView())

    def compose(self) -> ComposeResult:
        yield ChangingText(markup=False, id="delivery-summary")
        yield ChangingText(markup=False, id="delivery-history-summary")
        yield ChangingText(markup=False, id="delivery-error")

    def watch_delivery(self) -> None:
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        delivery = self.delivery
        self.display = delivery.shown or bool(delivery.error)
        if self.is_attached:
            summary = self.query_one("#delivery-summary", Static)
            summary.display = bool(delivery.current)
            summary.update(delivery.summary)
            historical = self.query_one("#delivery-history-summary", Static)
            historical.display = bool(delivery.notices)
            historical.update(delivery.notices_summary)
            error = self.query_one("#delivery-error", Static)
            error.display = bool(delivery.error)
            error.update(delivery.error)

    def on_mount(self) -> None:
        self._refresh_summary()


class HistoryView(ABC):
    inputs: tuple[HistoricalInput, ...] = ()

    @property
    @abstractmethod
    def load_offered(self) -> bool: ...


@dataclass(frozen=True)
class HiddenHistory(HistoryView):
    load_offered: ClassVar[bool] = True


@dataclass(frozen=True)
class ShownHistory(HistoryView):
    inputs: tuple[HistoricalInput, ...]
    load_offered: ClassVar[bool] = False


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
    delivery: var[DeliveryView] = var(DeliveryView())
    error: var[str] = var("")
    overview_text: var[str] = var("")

    def __init__(
        self,
        *,
        log_path: Path | None,
        load_history: Callable[[], Awaitable[tuple[HistoricalInput, ...]]],
        dismiss_history: Callable[[], Awaitable[None]],
    ):
        super().__init__()
        self.log_path = log_path
        self._load_history = load_history
        self._dismiss_history = dismiss_history
        self._history: HistoryView = HiddenHistory()
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Session details", markup=False)
            yield Static(markup=False, id="delivery-error")
            with VerticalScroll():
                overview = Static(self.overview_text, markup=False, id="session-overview")
                overview.display = bool(self.overview_text)
                yield overview
                yield Static(
                    "These inputs have no confirmed start. They may still be queued. "
                    "They are not automatically retried.",
                    markup=False,
                )
                yield Static(markup=False, id="delivery-records")
                yield Static(markup=False, id="delivery-historical-summary")
                yield Static(
                    "Earlier notices are not awaiting a start in the owner's current turn or queue, "
                    "or predate delivery tracking. A notice is not proof that an input is unread. "
                    "Clearing hides the notice only: it does not confirm delivery, mark messages "
                    "read, or retry inputs. Cleared notices remain available here.",
                    markup=False,
                    id="delivery-history-explanation",
                )
                yield DetailAction(
                    "Load earlier notices",
                    markup=False,
                    id="delivery-load-history",
                )
                yield DetailAction(
                    "Clear earlier notices",
                    markup=False,
                    id="delivery-clear-history",
                )
                yield Static(markup=False, id="delivery-historical-records")
            with HorizontalGroup():
                if self.log_path is not None:
                    yield Button(AcpLogLink.label, id="delivery-log")
                yield Button("Close (Esc)", id="delivery-close")

    def watch_delivery(self, old: DeliveryView, new: DeliveryView) -> None:
        if new.history_changed(old):
            self._history = HiddenHistory()
        self._refresh_records()

    def watch_overview_text(self, value: str) -> None:
        if self.is_mounted:
            overview = self.query_one("#session-overview", Static)
            overview.display = bool(value)
            overview.update(value)

    def watch_error(self) -> None:
        if self.is_attached:
            error = self.query_one("#delivery-error", Static)
            error.display = bool(self.delivery.error or self.error)
            error.update(self.delivery.error or self.error)

    def _refresh_records(self) -> None:
        if not self.is_attached:
            return
        self.watch_error()
        self.query_one("#delivery-records", Static).update(
            self.delivery.pending_records_text()
        )
        self.query_one("#delivery-historical-summary", Static).update(
            self.delivery.history_summary
        )
        self.query_one("#delivery-history-explanation").display = bool(
            self.delivery.notices
        )
        load = self.query_one("#delivery-load-history", DetailAction)
        load.display = bool(self.delivery.notices) and self._history.load_offered
        load.disabled = self._busy
        clear = self.query_one("#delivery-clear-history", DetailAction)
        clear.display = self.delivery.dismissible_notices
        clear.disabled = self._busy
        self.query_one("#delivery-historical-records", Static).update(
            self.delivery.records_text(self._history.inputs)
        )

    def on_mount(self) -> None:
        self._refresh_records()
        self.watch_error()

    async def _shown(self) -> HistoryView:
        return ShownHistory(await self._load_history())

    async def _cleared(self) -> HistoryView:
        await self._dismiss_history()
        return HiddenHistory()

    @on(DetailAction.Activated, "#delivery-load-history")
    async def load_history(self, event: DetailAction.Activated) -> None:
        await self.update_history(event, self._shown)

    @on(DetailAction.Activated, "#delivery-clear-history")
    async def clear_history(self, event: DetailAction.Activated) -> None:
        await self.update_history(event, self._cleared)

    async def update_history(
        self, event: DetailAction.Activated,
        operation: Callable[[], Awaitable[HistoryView]],
    ) -> None:
        event.stop()
        if self._busy:
            return
        self._busy = True
        self.error = ""
        self._refresh_records()
        try:
            self._history = await operation()
        finally:
            self._busy = False
            self._refresh_records()

    @on(Button.Pressed, "#delivery-close")
    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#delivery-log")
    async def open_log(self) -> None:
        if self.log_path is not None:
            app = self.app
            self.dismiss(None)
            await app.session_navigation.preview(self.log_path)
