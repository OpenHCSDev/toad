"""Which bus this Toad opens: this machine's own, one it holds a profile for, or one it finds.

The picker opens on what this machine already knows, which is instant, and asks the tailnet
afterwards, which is seconds of ssh: probing in compose would hold the dialog closed for as
long as the slowest peer takes to refuse.
"""

from __future__ import annotations

import time

from textual import on, work
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.widgets import Select, Static
from ui_theme.scheme import PrimaryColour

from toad.comms_root import BusChoice, DiscoveredPeer, PickerRow
from agent_comms.tailnet_buses import PeerBus
from agent_comms.transport.tools.tailnet import CommsTailnetBusesTool
from toad.screens.modal import CenteredScreen, DismissibleScreen, SurfacePanel
from toad.widget_actions import PriorityActions


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


class BusChoices(CenteredScreen, PriorityActions, DismissibleScreen[PickerRow]):
    """The buses this machine can open, dismissed with the row the reader picked.

    The picker does not relaunch: `CoreConnection.select` chooses at the process boundary,
    so its caller ends the application onto the choice. A machine holding no remote profile
    still sees its own bus named, because an empty list would leave the reader guessing
    whether the picker worked.
    """

    def __init__(self, rows: tuple[PickerRow, ...]) -> None:
        super().__init__()
        self.rows = rows

    @classmethod
    def offered(cls) -> BusChoices:
        """What this machine knows without asking anyone: instant."""
        return cls(BusChoice.offered(time.time()))

    def compose(self) -> ComposeResult:
        with BusPanel():
            yield BusPrompt("Open a bus · Esc returns")
            # Blank until the reader picks: a Select posts Changed when its initial value is
            # set, so starting on a row chose that row before the list had been read.
            yield Select(self.options(), allow_blank=True, prompt="Choose a bus")

    def options(self) -> list[tuple[str, int]]:
        return [(row.label(), index) for index, row in enumerate(self.rows)]

    def on_mount(self) -> None:
        self.discover()

    @work(exclusive=True, group="bus-discovery", thread=True)
    def discover(self) -> None:
        """Ask the tailnet after the dialog is up; each peer's own CLI owns its answer."""
        try:
            core = self.app.coordination_access.open_current().core
            found = core.call(CommsTailnetBusesTool())
        except (OSError, ValueError, RuntimeError) as error:
            self.app.call_from_thread(self.discovery_failed, str(error))
            return
        self.app.call_from_thread(self.discovered, found.peers)

    def discovery_failed(self, reason: str) -> None:
        if self.is_mounted:
            self.query_one(BusPrompt).update(f"Discovery: {reason} · Esc returns")

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
        self.query_one(Select).set_options(self.options())
        self.query_one(BusPrompt).update(
            f"Open a bus · {len(peers)} found on your tailnet · Esc returns")

    @on(Select.Changed)
    def picked(self, event: Select.Changed) -> None:
        """A picked row is the answer; the row itself says what picking it does."""
        match event.value:
            case int() as index:
                self.dismiss(self.rows[index])
