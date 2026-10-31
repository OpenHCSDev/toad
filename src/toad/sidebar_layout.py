"""One app-owned placement policy for independently movable sidebar surfaces."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.css.types import DockEdge
from textual.geometry import Offset, Region, Size, Spacing


class SidebarEdge(DeclaredFamily, affix="SidebarEdge"):
    """An edge owns its native geometry, resize axis and control placement."""

    dock: ClassVar[DockEdge]
    symbol: ClassVar[str]
    sign: ClassVar[int]
    minimum: ClassVar[int]
    conversation_minimum: ClassVar[int]
    collapsed_extent: ClassVar[int]

    @classmethod
    @abstractmethod
    def axis(cls) -> type[SidebarEdge]: ...

    @classmethod
    @abstractmethod
    def extent(cls, size: Size) -> int: ...

    @classmethod
    @abstractmethod
    def coordinate(cls, point: Offset) -> int: ...

    @classmethod
    @abstractmethod
    def origin(cls, viewport: int, offset: int, extent: int) -> int: ...

    @classmethod
    @abstractmethod
    def region(cls, size: Size, span: SidebarGeometry, occupied: Spacing) -> Region: ...

    @classmethod
    @abstractmethod
    def gutter(cls, extent: int) -> Spacing: ...

    @classmethod
    @abstractmethod
    def size_toggle(cls, toggle) -> None: ...

    @classmethod
    @abstractmethod
    def size_handle(cls, handle) -> None: ...

    @classmethod
    @abstractmethod
    def handle_text(cls, size: Size) -> str: ...

    @classmethod
    @abstractmethod
    def control_offset(cls, distance: int) -> Offset: ...

    @classmethod
    def opposite(cls) -> type[SidebarEdge]:
        return next(edge for edge in SidebarEdge.members_with(cls.axis()) if edge is not cls)

    @classmethod
    def controls_margin(cls) -> Spacing:
        return cls.opposite().gutter(cls.collapsed_extent + 1)

    @classmethod
    def toggle_symbol(cls, collapsed: bool) -> str:
        return (cls.opposite() if collapsed else cls).symbol

    @classmethod
    def order_key(cls, order: int) -> int:
        return cls.sign * order


class LeadingSidebarEdge:
    sign = 1

    @classmethod
    def origin(cls, viewport: int, offset: int, extent: int) -> int:
        return offset


class TrailingSidebarEdge:
    sign = -1

    @classmethod
    def origin(cls, viewport: int, offset: int, extent: int) -> int:
        return viewport - offset - extent


class WidthSidebarEdge(SidebarEdge):
    minimum = 18
    conversation_minimum = 24
    collapsed_extent = 3

    @classmethod
    def axis(cls) -> type[SidebarEdge]:
        return WidthSidebarEdge

    @classmethod
    def extent(cls, size: Size) -> int:
        return size.width

    @classmethod
    def coordinate(cls, point: Offset) -> int:
        return point.x

    @classmethod
    def region(cls, size: Size, span: SidebarGeometry, occupied: Spacing) -> Region:
        return Region(cls.origin(size.width, span.offset, span.extent), occupied.top,
                      span.extent, max(0, size.height - occupied.height))

    @classmethod
    def size_toggle(cls, toggle) -> None:
        toggle.styles.width, toggle.styles.height = cls.collapsed_extent, "1fr"

    @classmethod
    def size_handle(cls, handle) -> None:
        handle.styles.width, handle.styles.height = 1, "1fr"
        handle.styles.pointer = "ew-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "\n".join("│" for _ in range(size.height))

    @classmethod
    def control_offset(cls, distance: int) -> Offset:
        return Offset(-cls.sign * distance, 0)


class HeightSidebarEdge(SidebarEdge):
    minimum = 9
    conversation_minimum = 8
    collapsed_extent = 1

    @classmethod
    def axis(cls) -> type[SidebarEdge]:
        return HeightSidebarEdge

    @classmethod
    def extent(cls, size: Size) -> int:
        return size.height

    @classmethod
    def coordinate(cls, point: Offset) -> int:
        return point.y

    @classmethod
    def region(cls, size: Size, span: SidebarGeometry, occupied: Spacing) -> Region:
        return Region(0, cls.origin(size.height, span.offset, span.extent), size.width, span.extent)

    @classmethod
    def size_toggle(cls, toggle) -> None:
        toggle.styles.width, toggle.styles.height = "1fr", cls.collapsed_extent

    @classmethod
    def size_handle(cls, handle) -> None:
        handle.styles.width, handle.styles.height = "1fr", 1
        handle.styles.pointer = "ns-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "─" * size.width

    @classmethod
    def control_offset(cls, distance: int) -> Offset:
        return Offset(0, -cls.sign * distance)


class LeftSidebarEdge(LeadingSidebarEdge, WidthSidebarEdge):
    dock = "left"
    symbol = "<"

    @classmethod
    def gutter(cls, extent: int) -> Spacing:
        return Spacing(0, 0, 0, extent)


class RightSidebarEdge(TrailingSidebarEdge, WidthSidebarEdge):
    dock = "right"
    symbol = ">"

    @classmethod
    def gutter(cls, extent: int) -> Spacing:
        return Spacing(0, extent, 0, 0)


class TopSidebarEdge(LeadingSidebarEdge, HeightSidebarEdge):
    dock = "top"
    symbol = "↑"

    @classmethod
    def gutter(cls, extent: int) -> Spacing:
        return Spacing(extent, 0, 0, 0)


class BottomSidebarEdge(TrailingSidebarEdge, HeightSidebarEdge):
    dock = "bottom"
    symbol = "↓"

    @classmethod
    def gutter(cls, extent: int) -> Spacing:
        return Spacing(0, 0, extent, 0)


class SidebarShift(DeclaredFamily, affix="SidebarShift"):
    available = True

    @abstractmethod
    def apply(self, layout: SidebarLayout, identity: str, direction: type[SidebarEdge]) -> bool: ...

    @abstractmethod
    def tooltip(self, direction: type[SidebarEdge]) -> str: ...


class BlockedSidebarShift(SidebarShift):
    available = False

    def apply(self, layout, identity, direction):
        return False

    def tooltip(self, direction):
        return "Outside workspace edge"


class SwapSidebarShift(SidebarShift):
    def apply(self, layout, identity, direction):
        return layout.swap(identity)

    def tooltip(self, direction):
        return f"Swap with the sidebar toward {direction.declared_name}"


class MoveSidebarShift(SidebarShift):
    def apply(self, layout, identity, direction):
        return layout.move(identity, direction)

    def tooltip(self, direction):
        return f"Move sidebar to {direction.declared_name}"


class SidebarPlacementAction(DeclaredFamily, affix="SidebarPlacementAction"):
    classes = ""
    label: str

    @property
    def name(self) -> str:
        return self.declared_name

    @classmethod
    def offered(cls) -> Iterator[SidebarPlacementAction]:
        yield cls()

    @abstractmethod
    def apply(self, layout: SidebarLayout, identity: str) -> None: ...

    @abstractmethod
    def present(self, button, placement: SidebarPlacement,
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

    def apply(self, layout, identity):
        layout.shift(identity, self.direction)

    def present(self, button, placement, directions):
        action = directions[self.direction]
        button.display = action.available
        button.tooltip = action.tooltip(self.direction)


class FloatSidebarPlacementAction(SidebarPlacementAction):
    label = "Float"

    def apply(self, layout, identity):
        layout.float_mode(identity)

    def present(self, button, placement, directions):
        button.update("Push" if placement.floating else "Float", layout=False)
        button.tooltip = ("Push conversation text" if placement.floating
                          else "Float over conversation text")


@dataclass(frozen=True, slots=True)
class SidebarPlacement:
    side: type[SidebarEdge]
    order: int
    extent_percent: int
    floating: bool = False


@dataclass(frozen=True, slots=True)
class SidebarGeometry:
    offset: int
    extent: int


@dataclass(frozen=True, slots=True)
class ResolvedSidebarLayout:
    bars: dict[str, Region]
    gutter: Spacing


class SidebarLayout:
    """Placement only; sidebar content and thread navigation retain their owners."""

    minimum_percent = 15
    maximum_percent = 50

    def __init__(self) -> None:
        self.placements: dict[str, SidebarPlacement] = {
            "channels-sidebar": SidebarPlacement(LeftSidebarEdge, 0, 40),
            "thread-sidebar": SidebarPlacement(RightSidebarEdge, 0, 34),
        }

    def get(self, identity: str) -> SidebarPlacement:
        return self.placements[identity]

    def move(self, identity: str, side: type[SidebarEdge]) -> bool:
        current = self.get(identity)
        if current.side is side:
            return False
        peers = [key for key, placement in self.placements.items()
                 if key != identity and placement.side is side]
        self.placements[identity] = replace(current, side=side, order=len(peers))
        self._renumber(current.side)
        return True

    def swap(self, identity: str) -> bool:
        current = self.get(identity)
        peers = [key for key, placement in self.placements.items()
                 if key != identity and placement.side is current.side]
        if not peers:
            return False
        other = peers[0]
        self.placements[identity] = replace(current, order=self.placements[other].order)
        self.placements[other] = replace(self.placements[other], order=current.order)
        return True

    def directions(self, identity: str) -> dict[type[SidebarEdge], SidebarShift]:
        """Each spatial arrow swaps a neighbor, crosses the center or stops at a wall."""
        current = self.get(identity)
        actions: dict[type[SidebarEdge], SidebarShift] = {}
        for direction in SidebarEdge.members_with(SidebarEdge):
            if direction.axis() is not current.side.axis():
                actions[direction] = MoveSidebarShift()
                continue
            inward = direction is not current.side
            neighbor_order = current.order + (1 if inward else -1)
            if any(key != identity and peer.side is current.side and peer.order == neighbor_order
                   for key, peer in self.placements.items()):
                actions[direction] = SwapSidebarShift()
            elif inward:
                actions[direction] = MoveSidebarShift()
            else:
                actions[direction] = BlockedSidebarShift()
        return actions

    def shift(self, identity: str, direction: type[SidebarEdge]) -> bool:
        return self.directions(identity)[direction].apply(self, identity, direction)

    def resize(self, identity: str, percentage: int) -> bool:
        current = self.get(identity)
        percentage = max(self.minimum_percent, min(self.maximum_percent, percentage))
        if current.extent_percent == percentage:
            return False
        self.placements[identity] = replace(current, extent_percent=percentage)
        return True

    def float_mode(self, identity: str) -> bool:
        current = self.get(identity)
        self.placements[identity] = replace(current, floating=not current.floating)
        return self.placements[identity].floating

    def resolve(self, viewport: Size, collapsed: dict[str, bool]) -> ResolvedSidebarLayout:
        """Pack each axis once; top/bottom surfaces own the corners.

        Float changes only conversation clearance. A pushed inner peer clears
        its floating outer peer too; collapsed handles always reserve space.
        """
        spans: dict[str, SidebarGeometry] = {}
        occupied = gutter = Spacing()
        edges = SidebarEdge.members_with(SidebarEdge)
        for axis in dict.fromkeys(edge.axis() for edge in edges):
            total = max(0, axis.extent(viewport))
            extents = {
                key: axis.collapsed_extent if collapsed[key] else max(axis.minimum, total * placement.extent_percent // 100)
                for key, placement in self.placements.items()
                if key in collapsed and placement.side.axis() is axis
            }
            handles = sum(extent for key, extent in extents.items() if collapsed[key])
            expanded = [key for key in extents if not collapsed[key]]
            budget = max(total - axis.conversation_minimum,
                         min(total, handles + axis.minimum * len(expanded)))
            wanted = sum(extents[key] for key in expanded)
            available = max(0, budget - handles)
            if wanted > available:
                for key in expanded:
                    extents[key] = available * extents[key] // wanted
                for key in expanded[:available - sum(extents[key] for key in expanded)]:
                    extents[key] += 1
            if handles > total:
                for key in extents:
                    extents[key] = total * extents[key] // handles
            for side in SidebarEdge.members_with(axis):
                offset = clearance = 0
                for key in sorted((key for key in extents if self.get(key).side is side),
                                  key=lambda key: self.get(key).order):
                    extent = extents[key]
                    spans[key] = SidebarGeometry(offset, extent)
                    offset += extent
                    if collapsed[key] or not self.get(key).floating:
                        clearance = offset
                occupied += side.gutter(offset)
                gutter += side.gutter(clearance)
        return ResolvedSidebarLayout(
            {key: self.get(key).side.region(viewport, span, occupied) for key, span in spans.items()},
            gutter,
        )

    def _renumber(self, side: type[SidebarEdge]) -> None:
        names = sorted((key for key, placement in self.placements.items()
                        if placement.side is side), key=lambda key: self.placements[key].order)
        for index, key in enumerate(names):
            self.placements[key] = replace(self.placements[key], order=index)

    def ordered(self) -> tuple[str, ...]:
        edges = SidebarEdge.members_with(SidebarEdge)
        return tuple(sorted(self.placements, key=lambda key:
                            (edges.index(self.get(key).side),
                             self.get(key).side.order_key(self.get(key).order))))
