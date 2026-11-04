"""Where a sidebar can sit and which sidebar it is: the data both settings and layout read."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Self

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.css.types import DockEdge
from textual.geometry import Offset, Region, Size, Spacing
from textual.widget import Widget


class SidebarEdge(DeclaredFamily, affix="SidebarEdge"):
    """An edge owns its native geometry, resize axis and control placement."""

    dock: ClassVar[DockEdge]
    symbol: ClassVar[str]
    sign: ClassVar[int]
    minimum: ClassVar[int]
    conversation_minimum: ClassVar[int]
    collapsed_extent: ClassVar[int]
    """How many cells thick the collapsed bar is, across its edge."""

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
    def size_toggle(cls, toggle: Widget) -> None: ...

    @classmethod
    @abstractmethod
    def size_handle(cls, handle: Widget) -> None: ...

    @classmethod
    @abstractmethod
    def handle_text(cls, size: Size) -> str: ...

    @classmethod
    @abstractmethod
    def toggle_text(cls, collapsed: bool) -> str: ...

    @classmethod
    @abstractmethod
    def control_offset(cls, distance: int) -> Offset: ...

    @classmethod
    def opposite(cls) -> type[SidebarEdge]:
        return next(edge for edge in SidebarEdge.members_with(cls.axis()) if edge is not cls)

    @classmethod
    def content_padding(cls) -> Spacing:
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
    def size_toggle(cls, toggle: Widget) -> None:
        toggle.styles.width, toggle.styles.height = cls.collapsed_extent, "1fr"

    @classmethod
    def size_handle(cls, handle: Widget) -> None:
        handle.styles.width, handle.styles.height = 1, "1fr"
        handle.styles.pointer = "ew-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "\n".join("│" for _ in range(size.height))

    @classmethod
    def toggle_text(cls, collapsed: bool) -> str:
        return cls.toggle_symbol(collapsed)

    @classmethod
    def control_offset(cls, distance: int) -> Offset:
        return Offset(-cls.sign * distance, 0)


class HeightSidebarEdge(SidebarEdge):
    minimum = 9
    conversation_minimum = 8
    collapsed_extent = 2

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
    def size_toggle(cls, toggle: Widget) -> None:
        toggle.styles.width, toggle.styles.height = "1fr", cls.collapsed_extent

    @classmethod
    def size_handle(cls, handle: Widget) -> None:
        handle.styles.width, handle.styles.height = "1fr", 1
        handle.styles.pointer = "ns-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "─" * size.width

    @classmethod
    def toggle_text(cls, collapsed: bool) -> str:
        """One symbol on every row, so a two-row bar reads centred."""
        return "\n".join(cls.toggle_symbol(collapsed) for _ in range(cls.collapsed_extent))

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


@dataclass(frozen=True, slots=True)
class SidebarPlacement(DeclaredFamily, affix="SidebarPlacement"):
    """A nominal workspace role owns its initial policy and native spelling."""

    default_side: ClassVar[type[SidebarEdge]]
    default_extent_percent: ClassVar[int]

    side: type[SidebarEdge]
    order: int
    extent_percent: int
    floating: bool = False

    @classmethod
    def initial(cls) -> Self:
        return cls(cls.default_side, 0, cls.default_extent_percent)


class ChannelsSidebarPlacement(SidebarPlacement):
    default_side = LeftSidebarEdge
    default_extent_percent = 40


class ThreadSidebarPlacement(SidebarPlacement):
    default_side = RightSidebarEdge
    default_extent_percent = 34


@dataclass(frozen=True, slots=True)
class SidebarGeometry:
    offset: int
    extent: int
