"""One app-owned placement policy for the two independently movable sidebars."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

type Side = Literal["left", "right"]


@dataclass(frozen=True, slots=True)
class SidebarPlacement:
    side: Side
    order: int  # Zero is the outside edge; a second bar goes on its inside.
    width_percent: int
    floating: bool = False


class SidebarLayout:
    """Placement only; sidebar content and thread navigation retain their owners."""

    def __init__(self) -> None:
        self.placements: dict[str, SidebarPlacement] = {
            "channels-sidebar": SidebarPlacement("left", 0, 40),
            "thread-sidebar": SidebarPlacement("right", 0, 34),
        }

    def get(self, identity: str) -> SidebarPlacement:
        return self.placements[identity]

    def move(self, identity: str, side: Side) -> bool:
        if side not in {"left", "right"}:
            raise ValueError("Unknown sidebar edge.")
        current = self.get(identity)
        if current.side == side:
            return False
        peers = [key for key, placement in self.placements.items()
                 if key != identity and placement.side == side]
        self.placements[identity] = replace(current, side=side, order=len(peers))
        self._renumber(current.side)
        return True

    def swap(self, identity: str) -> bool:
        current = self.get(identity)
        peers = [key for key, placement in self.placements.items()
                 if key != identity and placement.side == current.side]
        if not peers:
            return False
        other = peers[0]
        self.placements[identity] = replace(current, order=self.placements[other].order)
        self.placements[other] = replace(self.placements[other], order=current.order)
        return True

    def width(self, identity: str, percentage: int) -> bool:
        if type(percentage) is not int:
            raise ValueError("Sidebar width must be an integer percentage.")
        current = self.get(identity)
        percentage = max(15, min(50, percentage))
        if current.width_percent == percentage:
            return False
        self.placements[identity] = replace(current, width_percent=percentage)
        return True

    def float_mode(self, identity: str) -> bool:
        current = self.get(identity)
        self.placements[identity] = replace(current, floating=not current.floating)
        if self.placements[identity].floating and current.order == 0:
            # A floating bar belongs inside the outer pushed bar, not over it.
            peer = next((key for key, placement in self.placements.items()
                         if key != identity and placement.side == current.side
                         and not placement.floating), None)
            if peer is not None:
                self.swap(identity)
        return self.placements[identity].floating

    def _renumber(self, side: Side) -> None:
        names = sorted((key for key, placement in self.placements.items()
                        if placement.side == side), key=lambda key: self.placements[key].order)
        for index, key in enumerate(names):
            self.placements[key] = replace(self.placements[key], order=index)

    def ordered(self) -> tuple[str, ...]:
        return tuple(sorted(self.placements, key=lambda key:
                            (self.placements[key].side != "left",
                             self.placements[key].order if self.placements[key].side == "left"
                             else -self.placements[key].order)))
