"""Bus choices and the native application capability that opens them."""

from __future__ import annotations

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from agent_comms.transport.connector_store import (
    HeldUiProfiles,
    OpenableProfile,
)
from agent_comms.transport.tailnet_buses import PeerHoldsBus
from textual.abstract_hooks import AbstractHooksMeta


class ProfileArgument:
    """The profile option shared by launch parsing and a bus choice's arguments."""

    argument: ClassVar[str] = "--comms-profile"


class BusPickerHost(metaclass=AbstractHooksMeta):
    """The application opens a chosen bus or asks a discovered peer for its profile."""

    @abstractmethod
    def open_bus(self, choice: BusChoice) -> None: ...

    @abstractmethod
    def ask_peer_for_profile(self, found: PeerHoldsBus) -> None: ...


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

    def removable(self) -> bool:
        """Whether a reader can take this row off the list. Nothing is, by default: this
        machine's own bus and a machine the tailnet reports are facts, not saved entries."""
        return False

    def remove(self) -> None:
        """Take this row off the list for good. Only a row that says it is removable."""
        raise TypeError(f"{type(self).__name__} is not a saved row")


class BusChoice(PickerRow):
    """A bus the next launch of this Toad selects.

    `CoreConnection.select` chooses once at the process boundary and tab scopes are
    written under that connection's location, so a reader changing bus relaunches onto
    their choice rather than re-parenting every observation in place. The choice owns
    how it writes itself into the next launch's arguments; nothing else spells them.
    """

    def chosen(self, app: BusPickerHost) -> None:
        """A bus is opened by ending this session onto it."""
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
    def offered(now: float) -> tuple[BusChoice, ...]:
        """This machine's own bus, then every remote one it holds an open profile for."""
        return (LocalBus(), *(
            HeldBus(entry) for entry in HeldUiProfiles.held(now)
            if isinstance(entry, OpenableProfile)
        ))


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

    def removable(self) -> bool:
        """A held profile is the saved entry, so this is the row that can be removed."""
        return True

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
