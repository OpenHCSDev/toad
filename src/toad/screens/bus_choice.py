"""Which bus this Toad opens: this machine's own, one it holds a profile for, or one it finds.

The picker opens on what this machine already knows, which is instant, and asks the tailnet
afterwards, which is seconds of ssh: probing in compose would hold the dialog closed for as
long as the slowest peer takes to refuse.
"""

from __future__ import annotations

import time

from agent_comms.transport.tailnet_buses import NamedHost, PeerBus
from agent_comms.transport.tools.tailnet import CommsTailnetBusesTool
from textual import on, work
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.document._editing import EditingMode
from textual.events import Mount
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from ui_theme.scheme import PrimaryColour

from toad.bus_selection import BusChoice, DiscoveredPeer, PickerRow
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


class BusAddress(FillWidth, Input):
    """Where a reader types a machine to add by hand.

    Tristan: let a bus be added by hand - type an address, save it, and be able to remove
    saved ones again. Submitting runs the same ask-for-profile flow a discovered peer runs,
    so there is no second way to open a bus; once the host hands a profile over it becomes
    an ordinary held row, and removing it is removing that profile.
    """


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


class ListsBuses(Widget):
    """The buses this machine can open, listed and kept current as the tailnet answers.

    Two places list them: the Open-bus dialog and the splash's own section. The rows, the
    discovery worker, which found peer replaces which held row, and what choosing one does
    are declared here once, so a bus cannot appear on the splash with different behaviour
    from the dialog (paper1 Thm 4.6: a copy of this in the second place would be paid again
    on every change to any of it).

    A member says where its rows go, how it tells a reader what discovery is doing, and
    whether it asks the tailnet at all. Starting discovery is deliberately NOT here: it is
    seconds of ssh to every peer, and the splash shows whenever there are no tabs open, so
    a base that discovered on mount swept the tailnet on every launch for a list nobody had
    asked to see. The dialog asks because the reader opened it to choose.
    """

    def __init__(self, rows: tuple[PickerRow, ...]) -> None:
        self.rows = rows
        super().__init__()

    @staticmethod
    def offered_rows() -> tuple[PickerRow, ...]:
        """What this machine knows without asking anyone: instant."""
        return BusChoice.offered(time.time())

    def bus_options(self) -> list[Option]:
        return [Option(row.label()) for row in self.rows]

    def say_discovery(self, found: int) -> None:
        """Tell a reader what the tailnet answered. A listing with nowhere to say it is
        free to say nothing; the dialog puts it in its prompt."""

    def say_failure(self, reason: str) -> None:
        """Tell a reader discovery could not run at all."""

    @work(exclusive=True, group="bus-discovery", thread=True)
    def discover(self) -> None:
        """Ask the tailnet after the listing is up; each peer's own CLI owns its answer."""
        try:
            core = self.app.coordination_access.open_current().core
            found = core.call(CommsTailnetBusesTool())
        except (OSError, ValueError, RuntimeError) as error:
            self.app.call_from_thread(self.discovery_failed, str(error))
            return
        self.app.call_from_thread(self.discovered, found.peers)

    def discovery_failed(self, reason: str) -> None:
        if self.is_mounted:
            self.say_failure(reason)

    def discovered(self, found: tuple[PeerBus, ...]) -> None:
        """Add the peers holding a bus, and drop the rows that were already them.

        A machine this one holds a profile for is also a machine the tailnet reports, so it
        was two rows: one named by its certificate and grant id, one by its hostname and
        thread count (Tristan: "histiry of last connected accunukates in the remote bus
        dialog"). The found row wins, because it says which machine and how much is on it,
        and picking it asks for a profile that replaces the one being dropped.
        """
        if not self.is_mounted:
            return
        peers = tuple(DiscoveredPeer(entry) for entry in found if entry.openable)
        if not peers:
            return
        covered = tuple(row for row in self.rows
                        if not any(row.same_bus(peer.found) for peer in peers))
        self.rows = (*covered, *peers)
        self.query_one(BusRows).clear_options().add_options(self.bus_options())
        self.say_discovery(len(peers))

    @on(OptionList.OptionSelected)
    def picked(self, event: OptionList.OptionSelected) -> None:
        """A chosen row is the answer; the row itself says what choosing it does."""
        self.chose(self.rows[event.option_index])

    def chose(self, row: PickerRow) -> None:
        """What this listing does with the chosen row."""
        row.chosen(self.app)

    @on(Input.Submitted)
    def typed_a_host(self, event: Input.Submitted) -> None:
        """A typed address is asked exactly as a discovered peer is asked."""
        event.stop()
        address = event.value.strip()
        if not address:
            return
        event.input.value = ""
        self.app.ask_peer_for_profile(NamedHost.typed(address))

    def forget_highlighted(self) -> None:
        """Take the highlighted row off the list, if it is a row a reader saved."""
        rows = self.query_one(BusRows)
        highlighted = rows.highlighted
        if highlighted is None:
            return
        row = self.rows[highlighted]
        if not row.removable():
            return
        row.remove()
        self.rows = (*self.rows[:highlighted], *self.rows[highlighted + 1:])
        rows.clear_options().add_options(self.bus_options())


class ForgetSavedBusAction(WidgetAction):
    """Forget the highlighted saved bus."""

    title = "Forget this bus"
    keys = {EditingMode: ("delete",)}
    show = True

    def apply(self, context: ListsBuses) -> None:
        context.forget_highlighted()


class BusChoices(CenteredScreen, PriorityActions, ListsBuses, DismissibleScreen[PickerRow],
                 actions=(ForgetSavedBusAction,), scopes={PriorityActions: (DismissAction,)}):
    """The buses this machine can open, dismissed with the row the reader picked.

    The picker does not relaunch: `CoreConnection.select` chooses at the process boundary,
    so its caller ends the application onto the choice. A machine holding no remote profile
    still sees its own bus named, because an empty list would leave the reader guessing
    whether the picker worked.
    """

    @classmethod
    def offered(cls) -> BusChoices:
        return cls(cls.offered_rows())

    def compose(self) -> ComposeResult:
        with BusPanel():
            yield BusPrompt("Open a bus · Delete forgets a saved one · Esc returns")
            yield BusRows(*self.bus_options())
            yield BusAddress(placeholder="Add a machine by name or address")

    @on(Mount)
    def on_mount(self) -> None:
        """The reader opened this to choose a bus, so this is where asking belongs."""
        self.discover()

    def say_discovery(self, found: int) -> None:
        self.query_one(BusPrompt).update(
            f"Open a bus · {found} found on your tailnet · Esc returns")

    def say_failure(self, reason: str) -> None:
        self.query_one(BusPrompt).update(f"Discovery: {reason} · Esc returns")

    def chose(self, row: PickerRow) -> None:
        """The dialog answers its caller rather than acting itself, so one place decides
        what a chosen row does for a dismissed picker too (app.picked_bus)."""
        self.dismiss(row)
