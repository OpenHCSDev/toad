"""One app-owned placement policy for independently movable sidebar surfaces."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.geometry import Region, Size, Spacing
from textual.widgets import Static

from toad.preferences import SETTINGS, SavedSettings
from toad.sidebar_placement import BandSplit, SidebarEdge, SidebarFold, SidebarGeometry, SidebarPlacement
from toad.terminal_origin import TerminalLayout, TerminalOrigin


class SidebarShift(DeclaredFamily, affix="SidebarShift"):
    available = True

    @abstractmethod
    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement], direction: type[SidebarEdge]) -> bool: ...

    @abstractmethod
    def tooltip(self, direction: type[SidebarEdge]) -> str: ...


class BlockedSidebarShift(SidebarShift):
    available = False

    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement], direction: type[SidebarEdge]) -> bool:
        return False

    def tooltip(self, direction: type[SidebarEdge]) -> str:
        return "Outside workspace edge"


class SwapSidebarShift(SidebarShift):
    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement], direction: type[SidebarEdge]) -> bool:
        return layout.swap(identity)

    def tooltip(self, direction: type[SidebarEdge]) -> str:
        return f"Swap with the sidebar toward {direction.declared_name}"


class MoveSidebarShift(SidebarShift):
    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement], direction: type[SidebarEdge]) -> bool:
        return layout.move(identity, direction)

    def tooltip(self, direction: type[SidebarEdge]) -> str:
        return f"Move sidebar to {direction.declared_name}"


class SidebarPlacementAction(DeclaredFamily, affix="SidebarPlacementAction"):
    classes = ""

    @property
    @abstractmethod
    def label(self) -> str: ...

    @property
    def name(self) -> str:
        return self.declared_name

    @classmethod
    def offered(cls) -> Iterator[SidebarPlacementAction]:
        yield cls()

    @abstractmethod
    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement]) -> None: ...

    @abstractmethod
    def present(self, button: Static, placement: SidebarPlacement,
                directions: dict[type[SidebarEdge], SidebarShift]) -> None: ...


@dataclass(frozen=True)
class DirectionalSidebarPlacementAction(SidebarPlacementAction):
    direction: type[SidebarEdge]
    classes = "-direction"

    @property
    def name(self) -> str:
        return self.direction.declared_name

    @property
    def label(self) -> str:
        return self.direction.symbol

    @classmethod
    def offered(cls) -> Iterator[SidebarPlacementAction]:
        for edge in SidebarEdge.members_with(SidebarEdge):
            yield cls(edge)

    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement]) -> None:
        layout.shift(identity, self.direction)

    def present(self, button: Static, placement: SidebarPlacement,
                directions: dict[type[SidebarEdge], SidebarShift]) -> None:
        action = directions[self.direction]
        button.display = action.available
        button.tooltip = action.tooltip(self.direction)


class FloatSidebarPlacementAction(SidebarPlacementAction):
    @property
    def label(self) -> str:
        return "Float"

    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement]) -> None:
        layout.float_mode(identity)

    def present(self, button: Static, placement: SidebarPlacement,
                directions: dict[type[SidebarEdge], SidebarShift]) -> None:
        button.update("Push" if placement.floating else "Float", layout=False)
        button.tooltip = ("Push conversation text" if placement.floating
                          else "Float over conversation text")


@dataclass(frozen=True, slots=True)
class ResolvedSidebarLayout:
    bars: dict[type[SidebarPlacement], Region]
    gutter: Spacing


class SidebarLayout:
    """Placement policy over the arrangement saved for this terminal origin.

    The settings own the placements: each role's saved record, or the role's
    own initial placement until the user moves or resizes it.
    """

    minimum_percent = 15
    maximum_percent = 50

    def __init__(self, settings: SavedSettings, origin: type[TerminalOrigin]) -> None:
        self.settings, self.origin = settings, origin

    @property
    def terminal(self) -> TerminalLayout:
        """This origin's saved arrangement, or an empty one until something is saved."""
        saved = (terminal for terminal in self.settings.current.layout.terminals
                 if terminal.origin is self.origin)
        return next(saved, TerminalLayout(self.origin))

    @property
    def placements(self) -> dict[type[SidebarPlacement], SidebarPlacement]:
        saved = {type(placement): placement for placement in self.terminal.placements}
        return {role: saved.get(role, role.initial()) for role in SidebarPlacement.members_with(SidebarPlacement)}

    def split(self, side: type[SidebarEdge]) -> int:
        """The first bar's share of the band on this edge."""
        saved = {split.side: split for split in self.terminal.splits}
        return saved.get(side, BandSplit(side)).percent

    def set_split(self, side: type[SidebarEdge], percent: int) -> bool:
        percent = max(0, min(100, percent))
        if self.split(side) == percent:
            return False
        others = tuple(split for split in self.terminal.splits if split.side is not side)
        self._save(replace(self.terminal, splits=(*others, BandSplit(side, percent))))
        return True

    def splits_after(self, identity: type[SidebarPlacement],
                     collapsed: Mapping[type[SidebarPlacement], bool]) -> bool:
        """Whether the next bar in this one's band sits beside it, so its splitter shows: bars
        whose folds take equal shares share a row; a folded strip under an open bar does not."""
        slot = self._slot(self.placements, identity)
        index = slot.index(identity)
        return any(SidebarFold.of(collapsed[identity]).shares == SidebarFold.of(collapsed[after]).shares
                   for after in slot[index + 1:index + 2])

    def _store(self, placements: dict[type[SidebarPlacement], SidebarPlacement]) -> None:
        self._save(replace(self.terminal, placements=tuple(placements.values())))

    def _save(self, terminal: TerminalLayout) -> None:
        others = tuple(saved for saved in self.settings.current.layout.terminals
                       if saved.origin is not self.origin)
        self.settings.set(SETTINGS.layout.terminals, (*others, terminal))

    def get(self, identity: type[SidebarPlacement]) -> SidebarPlacement:
        return self.placements[identity]

    def move(self, identity: type[SidebarPlacement], side: type[SidebarEdge]) -> bool:
        placements = self.placements
        current = placements[identity]
        if current.side is side:
            return False
        peers = [key for key, placement in placements.items()
                 if key != identity and placement.side is side]
        placements[identity] = replace(current, side=side, order=len(peers))
        self._renumber(placements, current.side)
        # Joining bars that share its room adopts one extent: the largest among them.
        slot = self._slot(placements, identity)
        extent = max(placements[key].extent_percent for key in slot)
        for key in slot:
            placements[key] = replace(placements[key], extent_percent=extent)
        self._store(placements)
        return True

    def swap(self, identity: type[SidebarPlacement]) -> bool:
        placements = self.placements
        current = placements[identity]
        peers = [key for key, placement in placements.items()
                 if key != identity and placement.side is current.side]
        if not peers:
            return False
        other = peers[0]
        placements[identity] = replace(current, order=placements[other].order)
        placements[other] = replace(placements[other], order=current.order)
        self._store(placements)
        return True

    def directions(self, identity: type[SidebarPlacement]) -> dict[type[SidebarEdge], SidebarShift]:
        """Each spatial arrow swaps the neighbour that lies that way, stops at the bar's own
        wall, or moves the bar to that edge. Where a neighbour lies is its edge's `onward`:
        inward for left and right columns, rightward along a top or bottom band."""
        placements = self.placements
        current = placements[identity]
        onward = current.side.onward()
        steps = {onward: 1, onward.opposite(): -1}
        orders = {peer.order for key, peer in placements.items()
                  if key != identity and peer.side is current.side}
        actions: dict[type[SidebarEdge], SidebarShift] = {}
        for direction in SidebarEdge.members_with(SidebarEdge):
            if direction in steps and current.order + steps[direction] in orders:
                actions[direction] = SwapSidebarShift()
            elif direction is current.side:
                actions[direction] = BlockedSidebarShift()
            else:
                actions[direction] = MoveSidebarShift()
        return actions

    def shift(self, identity: type[SidebarPlacement], direction: type[SidebarEdge]) -> bool:
        return self.directions(identity)[direction].apply(self, identity, direction)

    def resize(self, identity: type[SidebarPlacement], percentage: int) -> bool:
        placements = self.placements
        percentage = max(self.minimum_percent, min(self.maximum_percent, percentage))
        resized = self._slot(placements, identity)
        if all(placements[key].extent_percent == percentage for key in resized):
            return False
        for key in resized:
            placements[key] = replace(placements[key], extent_percent=percentage)
        self._store(placements)
        return True

    def float_mode(self, identity: type[SidebarPlacement]) -> bool:
        placements = self.placements
        current = placements[identity]
        placements[identity] = replace(current, floating=not current.floating)
        self._store(placements)
        return placements[identity].floating

    def resolve(self, viewport: Size, collapsed: dict[type[SidebarPlacement], bool]) -> ResolvedSidebarLayout:
        """Pack each axis once; top/bottom surfaces own the corners.

        Float changes only conversation clearance. A pushed inner peer clears
        its floating outer peer too; collapsed handles always reserve space.
        """
        placements = self.placements
        spans: dict[type[SidebarPlacement], SidebarGeometry] = {}
        occupied = gutter = Spacing()
        edges = SidebarEdge.members_with(SidebarEdge)
        for axis in dict.fromkeys(edge.axis() for edge in edges):
            total = max(0, axis.extent(viewport))
            sides = {
                side: sorted((key for key, placement in placements.items()
                              if key in collapsed and placement.side is side),
                             key=lambda key: placements[key].order)
                for side in SidebarEdge.members_with(axis)
            }
            slots = [slot for side, keys in sides.items() for slot in side.slots(keys)]
            folded = {slot: all(collapsed[key] for key in slot) for slot in slots}
            extents = {
                slot: axis.collapsed_extent if folded[slot] else max(
                    max(axis.minimum, total * placements[key].extent_percent // 100)
                    for key in slot if not collapsed[key])
                for slot in slots
            }
            handles = sum(extent for slot, extent in extents.items() if folded[slot])
            # Rounding goes in the placements' fixed order, so a swap keeps every extent.
            rank = {key: index for index, key in enumerate(placements)}
            expanded = sorted((slot for slot in extents if not folded[slot]),
                              key=lambda slot: min(rank[key] for key in slot))
            budget = max(total - axis.conversation_minimum,
                         min(total, handles + axis.minimum * len(expanded)))
            wanted = sum(extents[slot] for slot in expanded)
            available = max(0, budget - handles)
            if wanted > available:
                minimum = min(axis.minimum, available // len(expanded))
                surplus = available - minimum * len(expanded)
                demand = wanted - minimum * len(expanded)
                for slot in expanded:
                    extents[slot] = minimum + surplus * (extents[slot] - minimum) // demand
                for slot in expanded[:available - sum(extents[slot] for slot in expanded)]:
                    extents[slot] += 1
            if handles > total:
                for slot in extents:
                    extents[slot] = total * extents[slot] // handles
            for side, keys in sides.items():
                sized = {key: axis.collapsed_extent if collapsed[key] and not folded[slot] else extents[slot]
                         for slot in side.slots(keys) for key in slot}
                packed = dict(zip(keys, side.pack([sized[key] for key in keys],
                                                  [SidebarFold.of(collapsed[key]) for key in keys],
                                                  viewport, self.split(side))))
                spans.update(packed)
                reach = {key: span.offset + span.extent for key, span in packed.items()}
                occupied += side.gutter(max(reach.values(), default=0))
                gutter += side.gutter(max((reach[key] for key in keys
                                           if collapsed[key] or not placements[key].floating),
                                          default=0))
        return ResolvedSidebarLayout(
            {key: placements[key].side.region(viewport, span, occupied) for key, span in spans.items()},
            gutter,
        )

    @staticmethod
    def _slot(placements: dict[type[SidebarPlacement], SidebarPlacement],
              identity: type[SidebarPlacement]) -> tuple[type[SidebarPlacement], ...]:
        """The bars sharing identity's room on its edge, identity included."""
        side = placements[identity].side
        keys = sorted((key for key, placement in placements.items() if placement.side is side),
                      key=lambda key: placements[key].order)
        slot, = (slot for slot in side.slots(keys) if identity in slot)
        return slot

    @staticmethod
    def _renumber(placements: dict[type[SidebarPlacement], SidebarPlacement],
                  side: type[SidebarEdge]) -> None:
        names = sorted((key for key, placement in placements.items()
                        if placement.side is side), key=lambda key: placements[key].order)
        for index, key in enumerate(names):
            placements[key] = replace(placements[key], order=index)

    def ordered(self) -> tuple[type[SidebarPlacement], ...]:
        edges = SidebarEdge.members_with(SidebarEdge)
        placements = self.placements
        return tuple(sorted(placements, key=lambda key:
                            (edges.index(placements[key].side),
                             placements[key].side.order_key(placements[key].order))))
