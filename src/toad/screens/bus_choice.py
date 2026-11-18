"""Which bus this Toad opens: this machine's own, one it holds a profile for, or one it finds.

The picker opens on what this machine already knows, with the peers the tailnet last
reported, which is instant, and asks the tailnet again afterwards, which is seconds of ssh:
probing in compose would hold the dialog closed for as long as the slowest peer takes to
refuse.
"""

from __future__ import annotations

import time

from formbridge.key_declarations import TextEntryMode
from textual import on
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles

from textual.events import Mount
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from toad.client.sidebar_lines import BusChoiceLine
from ui_theme.scheme import PrimaryColour

from toad.client.bus_selection import (
    BusAddressEntry, BusChoice, BusListing, BusPickerHost, BusSwitcherPrompt, PickerRow, TailnetAnswer,
)
from toad.native_style import AutoHeight, FillWidth
from toad.screens.modal import CenteredScreen, DismissibleScreen, SurfacePanel
from toad.widget_actions import DismissAction, PriorityActions, WidgetAction


class BusPanel(SurfacePanel):
    native_theme = (NativeDeclaration.of(Styles.border, Keyword("round"), Variable(PrimaryColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        # A share of the window with a ceiling, like every other dialog here (QueuePanel):
        # a fixed 72 columns does not fit a phone-width terminal, and Tristan's did not.
        self.styles.width = "90%"
        self.styles.max_width = 72
        self.styles.height = "auto"
        self.styles.padding = (1, 2)


class BusPrompt(Static):
    """What the picker is for, above its rows."""


class BusAddress(BusAddressEntry, FillWidth, Input):
    """Where a reader types a machine to add by hand (`BusAddressEntry`)."""

    def __init__(self) -> None:
        super().__init__(placeholder=self.address_placeholder)

    def typed_address(self) -> str:
        return self.value

    def clear_address(self) -> None:
        self.value = ""

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit_address(self.app)


class BusOption(BusChoiceLine, Option):
    """A bus in the listing (the shared `BusChoiceLine`): its label, and choosing it does
    what its choice says, as Qt's `BusRow`."""

    def __init__(self, choice: PickerRow) -> None:
        self.choice = choice
        super().__init__(self.line_label())


class BusRows(AutoHeight, OptionList):
    """The buses, listed where they are rather than behind a dropdown.

    A Select is fewer lines and was the wrong shape twice over. It opens a second overlay
    inside this dialog, so at a phone's 40 columns the list renders straight through the
    panel's bottom border and over the sidebar behind it, and three rows that all fit on
    screen at once sit behind two steps and a broken-looking box (Tristan: "the bus menu
    does not work well on a narrow screen"). And a Select posts Changed the moment its
    initial value is set, which is why the old one had to start deliberately blank: here
    highlighting a row is not choosing it, so there is nothing to defend against.
    """

    ROWS = 10

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        # Tall enough for every bus a tailnet realistically holds, bounded so a long list
        # scrolls inside the panel instead of growing past the window.
        self.styles.max_height = self.ROWS


class ListsBuses(BusListing, Widget):
    """The buses this machine can open, as a Textual widget: the Open-bus dialog and the
    splash's own section.

    The rows, when the tailnet is asked, which found peer replaces which held row and what
    choosing one does are the shared BusListing's and the application's, so a bus cannot
    appear on the splash with different behaviour from the dialog or from the Qt welcome
    (paper1 Thm 4.6: a copy of any of it in a second place would be paid again on every
    change). This member draws them as BusRows and hears each answer the application gets.
    """

    rows: tuple[PickerRow, ...] = ()

    def picker_host(self) -> BusPickerHost:
        return self.app

    def held_rows(self) -> tuple[PickerRow, ...]:
        return BusChoice.offered(time.time())

    def bus_rows(self) -> BusRows:
        """The rows as they stand now, to compose."""
        self.rows = self.listed()
        return BusRows(*self.bus_options())

    def bus_options(self) -> list[Option]:
        return [BusOption(row) for row in self.rows]

    def show_rows(self, rows: tuple[PickerRow, ...]) -> None:
        self.rows = rows
        self.query_one(BusRows).clear_options().add_options(self.bus_options())

    @on(Mount)
    def hear_the_tailnet(self) -> None:
        self.app.tailnet_answers.subscribe(self, self.answered)

    def answered(self, answer: TailnetAnswer) -> None:
        if self.is_mounted:
            answer.shown_in(self)

    @on(OptionList.OptionSelected)
    def picked(self, event: OptionList.OptionSelected) -> None:
        """A chosen row is the answer; the row itself says what choosing it does."""
        self.chose(event.option)

    def chose(self, option: BusOption) -> None:
        """What this listing does with the chosen line: what its choice says."""
        option.choose(self.app)

    def forget_highlighted(self) -> None:
        """Forget the highlighted row, if it is a row a reader saved."""
        highlighted = self.query_one(BusRows).highlighted
        if highlighted is not None:
            self.forget(self.rows[highlighted])


class ForgetSavedBusAction(WidgetAction):
    """Forget the highlighted saved bus."""

    title = "Forget this bus"
    keys = {TextEntryMode: ("delete",)}
    show = True

    def apply(self, context: ListsBuses) -> None:
        context.forget_highlighted()


class BusChoices(CenteredScreen, PriorityActions, ListsBuses, DismissibleScreen[PickerRow],
                 actions=(ForgetSavedBusAction,), scopes={PriorityActions: (DismissAction,)}):
    """The buses this machine can open, dismissed with the row the reader picked.

    The picker only answers which row: its caller (app.picked_bus) lets the row act, and a
    chosen bus switches the running app onto it. A machine holding no remote profile still
    sees its own bus named, because an empty list would leave the reader guessing whether
    the picker worked.
    """

    def compose(self) -> ComposeResult:
        with BusPanel():
            yield BusPrompt(BusSwitcherPrompt.initial())
            yield self.bus_rows()
            yield BusAddress()

    @on(Mount)
    def ask_again(self) -> None:
        """The reader opened this to choose a bus, so the tailnet is asked again."""
        self.app.discover_buses()

    def say_discovery(self, found: int) -> None:
        self.query_one(BusPrompt).update(BusSwitcherPrompt.discovery(found))

    def say_failure(self, reason: str) -> None:
        self.query_one(BusPrompt).update(BusSwitcherPrompt.failure(reason))

    def chose(self, option: BusOption) -> None:
        """The dialog answers its caller rather than acting itself, so one place decides
        what a chosen row does for a dismissed picker too (app.picked_bus)."""
        self.dismiss(option.choice)
