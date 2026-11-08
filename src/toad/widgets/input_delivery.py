"""Server-owned current delivery state and dismissible historical notices."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalScroll
from textual.css.native import Keyword, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.reactive import var
from toad.widgets.acting_button import ActingButton, DismissButton
from toad.screens.modal import DismissibleScreen
from textual.widgets import Static

from agent_comms.input_attempt import HistoricalInput
from agent_comms.ui_model.delivery import DeliveryView
from toad.project_link import AcpLogLink
from toad.widgets.selection import ChangingText, InlineSelection
from toad.widget_actions import VisibleActions, Activates
from rich.style import Style as RichStyle
from ui_theme.scheme import (
    AccentColour,
    BackgroundColour,
    PrimaryColour,
    WarningColour,
)

from toad.native_style import (
    AutoHeight,
    AutoWidth,
    CenteredChildren,
    FillHeight,
    FillWidth,
    MutedText,
    OneRow,
    PointerCursor,
    SidePadding,
    SpacedBelow,
    SurfaceBackground,
)
from textual.events import Mount
from textual import on


class DetailAction(
    VisibleActions,
    Activates,
    InlineSelection,
    AutoWidth,
    OneRow,
    PointerCursor,
    Static,
    can_focus=True,
):
    """An inline detail action owns keyboard, pointer and activation behavior."""

    highlighted_text_style = RichStyle(bold=True, reverse=True)

    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(AccentColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (0, 0, 0, 1)
        self.styles.text_style = "underline"

    @abstractmethod
    async def act(self) -> None: ...

    def activate(self) -> None:
        if not self.disabled:
            self.call_next(self.act)


class DeliveryBarText(FillWidth, AutoHeight, ChangingText):
    """One delivery fact in the bar: it takes the bar's remaining width."""



class DeliveryBarError(DeliveryBarText):
    native_theme = (NativeDeclaration.of(Styles.color, Variable(WarningColour.name)),)


class InputDeliveryBar(AutoHeight, SidePadding, HorizontalGroup):
    delivery: var[DeliveryView] = var(DeliveryView())


    def compose(self) -> ComposeResult:
        """Only what the status title above cannot say: a failure to read delivery at all.

        The counts used to be previewed here as well, in two widgets whose separator lived
        inside one of their strings, directly under a status title already listing the same
        counts. Tristan, 2026-11-08: fold the duplicated delivery preview into the expanded
        status. The title owns the line now; this row owns the failure.
        """
        yield DeliveryBarError(markup=False)

    def watch_delivery(self) -> None:
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        delivery = self.delivery
        self.display = bool(delivery.error)
        if self.is_attached:
            error = self.query_one(DeliveryBarError)
            error.display = bool(delivery.error)
            error.update(delivery.error)

    @on(Mount)
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


class DetailsFrame(SurfaceBackground, Vertical):
    native_theme = (NativeDeclaration.of(Styles.border, Keyword("solid"), Variable(PrimaryColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "90%"
        self.styles.height = "85%"
        self.styles.padding = 1


class DetailsBody(FillHeight, VerticalScroll):
    """Its look is its bases."""


class DetailsRow(SpacedBelow, AutoHeight):
    """Every text row and action of the details is separated by one blank line."""



class DetailsText(DetailsRow, Static):
    pass


class DetailsError(DetailsText):
    native_theme = (NativeDeclaration.of(Styles.color, Variable(WarningColour.name)),)


class DetailsHistoricalSummary(MutedText, DetailsText):
    """Its look is its bases."""


class DetailsAction(DetailsRow, DetailAction):
    pass


class LoadHistory(DetailsAction):
    """Reads the earlier notices."""

    async def act(self) -> None:
        await self.query_ancestor(InputDeliveryDetails).load_history()


class ClearHistory(DetailsAction):
    """Hides the earlier notices."""

    async def act(self) -> None:
        await self.query_ancestor(InputDeliveryDetails).clear_history()


class SessionOverview(DetailsText):
    """The session facts above the delivery records."""


class PendingExplanation(DetailsText):
    """Why inputs without a confirmed start are listed."""


class DeliveryRecords(DetailsText):
    """The inputs awaiting a start."""


class HistoryExplanation(DetailsText):
    """What earlier notices are and are not."""


class HistoricalRecords(DetailsText):
    """The earlier notices, once loaded."""


class OpenLogButton(ActingButton):
    """Opens the agent log behind the delivery."""

    async def act(self) -> None:
        await self.query_ancestor(InputDeliveryDetails).open_log()


class InputDeliveryDetails(CenteredChildren, DismissibleScreen[None]):
    native_theme = (
        NativeDeclaration.of(Styles.background, Variable(BackgroundColour.name), Percent(40)),
    )
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
        with DetailsFrame():
            yield DetailsText("Session details", markup=False)
            yield DetailsError(markup=False)
            with DetailsBody():
                overview = SessionOverview(self.overview_text, markup=False)
                overview.display = bool(self.overview_text)
                yield overview
                yield PendingExplanation(
                    "These inputs have no confirmed start. They may still be queued. "
                    "They are not automatically retried.",
                    markup=False,
                )
                yield DeliveryRecords(markup=False)
                yield DetailsHistoricalSummary(markup=False)
                yield HistoryExplanation(
                    "Earlier notices are not awaiting a start in the owner's current turn or queue, "
                    "or predate delivery tracking. A notice is not proof that an input is unread. "
                    "Clearing hides the notice only: it does not confirm delivery, mark messages "
                    "read, or retry inputs. Cleared notices remain available here.",
                    markup=False,
                )
                yield LoadHistory("Load earlier notices", markup=False)
                yield ClearHistory("Clear earlier notices", markup=False)
                yield HistoricalRecords(markup=False)
            with HorizontalGroup():
                if self.log_path is not None:
                    yield OpenLogButton(AcpLogLink.label)
                yield DismissButton("Close")

    def watch_delivery(self, old: DeliveryView, new: DeliveryView) -> None:
        if new.history_changed(old):
            self._history = HiddenHistory()
        self._refresh_records()

    def watch_overview_text(self, value: str) -> None:
        if self.is_mounted:
            overview = self.query_one(SessionOverview)
            overview.display = bool(value)
            overview.update(value)

    def watch_error(self) -> None:
        if self.is_attached:
            error = self.query_one(DetailsError)
            error.display = bool(self.delivery.error or self.error)
            error.update(self.delivery.error or self.error)

    def _refresh_records(self) -> None:
        if not self.is_attached:
            return
        self.watch_error()
        self.query_one(PendingExplanation).display = bool(self.delivery.current)
        self.query_one(DeliveryRecords).update(
            self.delivery.pending_records_text()
        )
        self.query_one(DetailsHistoricalSummary).update(
            self.delivery.history_summary
        )
        self.query_one(HistoryExplanation).display = bool(
            self.delivery.notices
        )
        load = self.query_one(LoadHistory)
        load.display = bool(self.delivery.notices) and self._history.load_offered
        load.disabled = self._busy
        clear = self.query_one(ClearHistory)
        clear.display = self.delivery.dismissible_notices
        clear.disabled = self._busy
        self.query_one(HistoricalRecords).update(
            self.delivery.records_text(self._history.inputs)
        )

    @on(Mount)
    def on_mount(self) -> None:
        self._refresh_records()
        self.watch_error()

    async def _shown(self) -> HistoryView:
        return ShownHistory(await self._load_history())

    async def _cleared(self) -> HistoryView:
        await self._dismiss_history()
        return HiddenHistory()

    async def load_history(self) -> None:
        await self.update_history(self._shown)

    async def clear_history(self) -> None:
        await self.update_history(self._cleared)

    async def update_history(self, operation: Callable[[], Awaitable[HistoryView]]) -> None:
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

    async def open_log(self) -> None:
        if self.log_path is not None:
            app = self.app
            self.dismiss(None)
            await app.session_navigation.preview(self.log_path)
