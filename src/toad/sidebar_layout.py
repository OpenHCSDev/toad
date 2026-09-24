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


@dataclass(frozen=True, slots=True)
class SidebarGeometry:
    x: int
    width: int


@dataclass(frozen=True, slots=True)
class ResolvedSidebarLayout:
    bars: dict[str, SidebarGeometry]
    left_gutter: int
    right_gutter: int


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

    def directions(self, identity: str) -> dict[Side, Literal["move", "swap"] | None]:
        """Resolve spatial arrows against the current neighbors and outside wall."""
        current = self.get(identity)
        actions: dict[Side, Literal["move", "swap"] | None] = {"left": None, "right": None}
        for direction in actions:
            inward = direction != current.side
            neighbor_order = current.order + (1 if inward else -1)
            if any(key != identity and peer.side == current.side and peer.order == neighbor_order
                   for key, peer in self.placements.items()):
                actions[direction] = "swap"
            elif inward:
                actions[direction] = "move"
        return actions

    def shift(self, identity: str, direction: Side) -> bool:
        """One arrow step: swap with a neighbor, cross the center, or stop at a wall."""
        action = self.directions(identity)[direction]
        if action == "swap":
            return self.swap(identity)
        if action == "move":
            return self.move(identity, direction)
        return False

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
        return self.placements[identity].floating

    def resolve(self, viewport: int, collapsed: dict[str, bool]) -> ResolvedSidebarLayout:
        """Pack actual bar widths; Float changes only the conversation's gutter.

        An inner pushed bar reserves space through its inside edge, including
        any outer floating peer. Otherwise conversation text would overlap the
        pushed bar. Collapsed handles always reserve their small edge extent.
        """
        viewport = max(0, viewport)
        widths = {key: 3 if collapsed[key] else max(18, viewport * self.get(key).width_percent // 100)
                  for key in self.placements if key in collapsed}
        handles = sum(width for key, width in widths.items() if collapsed[key])
        expanded = [key for key in widths if not collapsed[key]]
        budget = max(viewport - 24, min(viewport, handles + 18 * len(expanded)))
        wanted = sum(widths[key] for key in expanded)
        available = max(0, budget - handles)
        if wanted > available:
            for key in expanded:
                widths[key] = available * widths[key] // wanted
            for key in expanded[:available - sum(widths[key] for key in expanded)]:
                widths[key] += 1
        if handles > viewport:
            for key in widths:
                widths[key] = viewport * widths[key] // handles
        bars: dict[str, SidebarGeometry] = {}
        gutters = {"left": 0, "right": 0}
        for side in ("left", "right"):
            offset = 0
            for key in sorted((key for key in widths if self.get(key).side == side),
                              key=lambda key: self.get(key).order):
                width = widths[key]
                bars[key] = SidebarGeometry(offset if side == "left" else viewport - offset - width,
                                            width)
                offset += width
                if collapsed[key] or not self.get(key).floating:
                    gutters[side] = offset
        return ResolvedSidebarLayout(bars, gutters["left"], gutters["right"])

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
