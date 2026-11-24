"""Bus choices and the native application capability that opens them."""

from __future__ import annotations

import time
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar

from agent_comms.transport.connector_profile import UiConnectionProfile
from agent_comms.transport.held_ui_profiles import (
    HeldUiProfiles,
    OpenableProfile,
)
from agent_comms.transport.tailnet_buses import NamedHost, PeerBus, PeerHoldsBus

from toad.client.menu_entry import MenuEntry


def held_profile_path(profile: UiConnectionProfile) -> Path:
    """Where this machine holds ``profile``: ``<host>-<grant_id>.json`` under
    ``HeldUiProfiles.directory()``, matching ``agent-comms-connector hold-ui``."""
    match profile.endpoint.url.host:
        case str() as host:
            return HeldUiProfiles.directory() / f"{host}-{profile.credential.grant_id}.json"
        case _:
            raise ValueError(f"{profile.endpoint.url} names no host to hold it under")


def hold_ui_profile(profile: UiConnectionProfile) -> Path:
    """Store a decoded UI profile privately under ``HeldUiProfiles.directory()`` using the
    same filename and atomic private write as ``agent-comms-connector hold-ui``, without
    importing the server-side connector CLI."""
    return profile.write_new(held_profile_path(profile))


def openable_held(now: float) -> tuple[OpenableProfile, ...]:
    """Every held UI profile this machine can open: filters `HeldUiProfiles.held` to its
    `OpenableProfile` members (other members are expired or unreadable). Shared helper so
    callers don't restate the `isinstance(entry, OpenableProfile)` guard."""
    return tuple(entry for entry in HeldUiProfiles.held(now)
                 if isinstance(entry, OpenableProfile))


class ProfileArgument:
    """The profile option shared by launch parsing and a bus choice's arguments."""

    argument: ClassVar[str] = "--comms-profile"


class BusPickerHost:
    """The application opens a chosen bus or asks a peer for its profile, and holds what the
    tailnet last said about its peers.

    A plain parent: the native app brings its toolkit metaclass.
    """

    found_buses: tuple[PeerBus, ...] = ()
    """The peers the tailnet last reported; nothing until it first answers."""

    def open_bus(self, choice: BusChoice) -> None:
        raise NotImplementedError

    def ask_peer_for_profile(self, found: PeerBus) -> None:
        raise NotImplementedError

    def ask_typed_host(self, typed: str) -> None:
        """A machine a reader typed is asked exactly as a discovered peer is asked, so there
        is no second way into a bus; blank text names no machine and asks nobody."""
        if address := typed.strip():
            self.ask_peer_for_profile(NamedHost.typed(address))


class BusAddressEntry:
    """The field a reader types a machine into, in either frontend's bus listing: what it
    asks for, and that submitting asks the host for that machine and empties the field.

    Tristan: let a bus be added by hand - type an address, save it, and be able to remove
    saved ones again. Submitting runs the same ask-for-profile flow a discovered peer runs,
    so there is no second way to open a bus; once the host hands a profile over it becomes
    an ordinary held row, and removing it is removing that profile.
    """

    address_placeholder: ClassVar[str] = "Add a machine by name or address"

    @abstractmethod
    def typed_address(self) -> str: ...

    @abstractmethod
    def clear_address(self) -> None: ...

    def submit_address(self, host: BusPickerHost) -> None:
        host.ask_typed_host(self.typed_address())
        self.clear_address()


class PickerRow(ABC):
    """One row the bus picker shows, and what picking it does.

    A bus this Toad can open and a peer it has only discovered are both rows, and they do
    different things when picked. Each says which, so the picker calls the row rather than
    asking what kind it is.
    """

    @abstractmethod
    def label(self) -> str:
        """How the picker names this row in one line."""

    @abstractmethod
    def chosen(self, app: BusPickerHost) -> None:
        """What picking this row does."""

    def same_bus(self, found: PeerHoldsBus) -> bool:
        """Whether this row is already that machine's bus, so the picker shows one row for
        it. Most rows are not any machine the tailnet reports; the ones that are say so."""
        return False

    def held_actions(self, listing: BusListing) -> tuple[MenuEntry, ...]:
        """What a listing offers on this row besides choosing it, where a finger is held on
        it or a mouse right-clicks it. Nothing, by default: this machine's own bus and a
        machine the tailnet reports are facts, not saved entries."""
        return ()

    def remove(self) -> None:
        """Take this row off the list for good. A row nobody saved has nothing to take
        away, so forgetting it leaves it listed."""

    @staticmethod
    def with_found(rows: tuple[PickerRow, ...], found: tuple[PeerBus, ...]) -> tuple[PickerRow, ...]:
        """``rows`` with the peers the tailnet reports holding a bus, each replacing the row
        that was already it.

        A machine this one holds a profile for is also a machine the tailnet reports, so it
        was two rows: one named by its certificate and grant id, one by its hostname and
        thread count (Tristan: "histiry of last connected accunukates in the remote bus
        dialog"). The found row wins, because it says which machine and how much is on it,
        and picking it asks for a profile that replaces the one being dropped.
        """
        peers = tuple(DiscoveredPeer(row) for entry in found for row in entry.openable())
        covered = tuple(row for row in rows if not any(row.same_bus(peer.found) for peer in peers))
        return (*covered, *peers)


class BusChoice(PickerRow):
    """A bus this Toad can switch onto.

    Switching swaps the connection, not the app: the running application reads the
    choice's launch arguments with the parser a launch uses, observes the new Core through
    its one coordination access and opens the tabs saved under that Core's location
    (ClientApplication.switch_bus). The choice owns how it writes itself into launch
    arguments; nothing else spells them.
    """

    def chosen(self, app: BusPickerHost) -> None:
        """A bus is opened by switching this session onto it."""
        app.open_bus(self)

    @abstractmethod
    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        """``argv`` rewritten so the next launch opens this bus."""

    @staticmethod
    def without_profile(argv: Sequence[str]) -> tuple[str, ...]:
        """``argv`` with every profile selection removed, so one launch names one bus."""
        remaining = list(argv)
        while ProfileArgument.argument in remaining:
            index = remaining.index(ProfileArgument.argument)
            del remaining[index:index + 2]
        return tuple(remaining)

    @staticmethod
    def held(now: float) -> tuple[HeldBus, ...]:
        """Every remote bus this machine holds an open profile for."""
        return tuple(HeldBus(entry) for entry in openable_held(now))

    @staticmethod
    def offered(now: float) -> tuple[BusChoice, ...]:
        """This machine's own bus, then the remote ones it holds."""
        return (LocalBus(), *BusChoice.held(now))


@dataclass(frozen=True)
class LocalBus(BusChoice):
    """This machine's own bus, which a launch opens when it names no profile."""

    def label(self) -> str:
        return "This machine"

    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        return self.without_profile(argv)


@dataclass(frozen=True)
class HeldBus(BusChoice):
    """A remote bus this machine holds an unexpired profile for."""

    profile: OpenableProfile

    def label(self) -> str:
        return self.profile.label()

    def same_bus(self, found: PeerHoldsBus) -> bool:
        """The route this profile was held with names the address it was reached on, which
        is the address the tailnet reports for that machine."""
        return self.profile.profile.route.reaches(found.peer.address)

    def arguments(self, argv: Sequence[str]) -> tuple[str, ...]:
        return (*self.without_profile(argv),
                ProfileArgument.argument, str(self.profile.path))

    def held_actions(self, listing: BusListing) -> tuple[MenuEntry, ...]:
        """A held profile is the saved entry, so this is the row a reader can forget, as
        Delete forgets it in the Textual picker."""
        return (MenuEntry("Forget this bus", partial(listing.forget, self)),)

    def remove(self) -> None:
        """Forget this bus: the profile file IS the saved entry, so deleting it is the
        removal. Tristan: type an address, save it, and be able to remove saved ones
        again - and HeldUiProfiles.held already lists exactly the files in that directory,
        so there is no second record of what is saved to keep in step."""
        self.profile.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class DiscoveredPeer(PickerRow):
    """A tailnet machine holding a bus this one has no profile for yet.

    Picking it asks that machine for one. It had to say "grant one over there and hold it
    here" while the hoop it described was a person carrying a file between two machines that
    can already talk.
    """

    found: PeerHoldsBus

    def label(self) -> str:
        return self.found.label()

    def chosen(self, app: BusPickerHost) -> None:
        """Ask it for a profile and open it: a bus on your own tailnet needs no errand.

        Tristan: "it's a bus on my private tailnet why would want to have to jupm throuhg
        hoops". The peer decides whether its endpoint is tailnet-only and says no itself
        when it is not (agent_comms.transport.served_endpoints.ProfileOffer).
        """
        app.ask_peer_for_profile(self.found)


class BusListing:
    """A list of the buses a reader can open: the Textual splash and Open-bus dialog, and the
    Qt welcome.

    Every listing shows the same rows: what this machine holds, with the peers the tailnet
    last reported (BusPickerHost.found_buses) merged in by PickerRow.with_found. When to ask
    the tailnet and what it last answered belong to the application, which asks once when
    its window opens and again when a reader opens a picker to choose
    (ClientApplication.discover_buses); a listing shows the last answer meanwhile and draws
    each new one (TailnetAnswer). A member says which held rows it starts from, which host
    it lists for, and where its rows go.

    A plain parent: each frontend's widget brings its toolkit metaclass.
    """

    buses_title = "Buses"
    """The title over the rows, wherever a listing draws one."""

    def picker_host(self) -> BusPickerHost:
        """The application this listing opens buses in."""
        raise NotImplementedError

    def held_rows(self) -> tuple[PickerRow, ...]:
        """What this machine knows without asking anyone, instantly: its own bus and the
        remote profiles it holds. The tailnet's reported peers are merged in by `listed()`."""
        return BusChoice.offered(time.time())

    def show_rows(self, rows: tuple[PickerRow, ...]) -> None:
        """Draw ``rows`` in place of the ones shown."""
        raise NotImplementedError

    def listed(self) -> tuple[PickerRow, ...]:
        """The rows as they stand now."""
        return PickerRow.with_found(self.held_rows(), self.picker_host().found_buses)

    def relist(self) -> None:
        self.show_rows(self.listed())

    def forget(self, row: PickerRow) -> None:
        """Take ``row`` off the list if a reader saved it; any other row stays listed."""
        row.remove()
        self.relist()

    def say_discovery(self, found: int) -> None:
        """Tell a reader how many buses the tailnet answered with. A listing with nowhere to
        say it says nothing; the dialog puts it in its prompt."""

    def say_failure(self, reason: str) -> None:
        """Tell a reader the tailnet could not be asked."""


class BusSwitcherPrompt:
    """Status-line text a modal bus switcher shows above its rows.

    Both frontends' switcher dialogs read from here so the line stays identical
    across Qt and Textual. The texts are the ones Textual's `BusChoices`
    inlined before this helper existed — keep the wording in one place so a
    rename to "Open a bus" / "Discovery:" in one frontend doesn't quietly
    drift from the other (paper1 Thm 4.6: a copy in a second place would be
    paid on every rename).
    """

    @staticmethod
    def initial() -> str:
        """What the switcher shows before the tailnet has answered."""
        return "Open a bus · asking the tailnet · Esc returns"

    @staticmethod
    def discovery(found: int) -> str:
        """Tailnet answered with ``found`` openable buses."""
        return f"Open a bus · {found} found on your tailnet · Esc returns"

    @staticmethod
    def failure(reason: str) -> str:
        """Tailnet could not be asked; the reason goes in the line."""
        return f"Discovery: {reason} · Esc returns"


class TailnetAnswer(ABC):
    """What the tailnet said when the application asked it, shown in each open listing."""

    @abstractmethod
    def shown_in(self, listing: BusListing) -> None: ...


@dataclass(frozen=True)
class BusesFound(TailnetAnswer):
    """The tailnet answered; its peers are now the application's found_buses."""

    found: tuple[PeerBus, ...]

    def shown_in(self, listing: BusListing) -> None:
        listing.relist()
        listing.say_discovery(sum(len(entry.openable()) for entry in self.found))


@dataclass(frozen=True)
class TailnetUnanswered(TailnetAnswer):
    """The tailnet could not be asked; what was found before stays listed."""

    reason: str

    def shown_in(self, listing: BusListing) -> None:
        listing.say_failure(self.reason)
