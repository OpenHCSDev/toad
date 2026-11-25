"""Where a sidebar can sit and which sidebar it is: the data both settings and layout read."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from itertools import accumulate
from operator import attrgetter
from typing import ClassVar, Protocol, Self

from agent_comms.nominal.declared_family import DeclaredFamily
from textual.css.types import DockEdge
from textual.geometry import Offset, Region, Size, Spacing


class _ControlStyles(Protocol):
    width: int | str
    height: int | str
    pointer: str


class StyledControl(Protocol):
    """A Textual toggle or resize handle whose layout styles an edge sizes."""

    styles: _ControlStyles


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
    def pack(cls, extents: Sequence[int], folds: Sequence[type[SidebarFold]], viewport: Size,
             split: int) -> tuple[SidebarGeometry, ...]:
        """Where this side's bars go, in their order, given each one's extent and fold and the
        first open bar's share of a shared band (BandSplit.percent): how bars sharing an edge
        share its room."""

    @classmethod
    @abstractmethod
    def slots[K](cls, keys: Sequence[K]) -> tuple[tuple[K, ...], ...]:
        """This side's bars, in order, grouped by the room they share: each group takes
        one extent along the axis."""

    @classmethod
    @abstractmethod
    def onward(cls) -> type[SidebarEdge]:
        """The arrow pointing from a bar on this edge toward the next one in order."""

    @classmethod
    @abstractmethod
    def gutter(cls, extent: int) -> Spacing: ...

    @classmethod
    @abstractmethod
    def size_toggle(cls, toggle: StyledControl) -> None: ...

    @classmethod
    @abstractmethod
    def size_handle(cls, handle: StyledControl) -> None: ...

    @classmethod
    @abstractmethod
    def handle_text(cls, size: Size) -> str: ...

    @classmethod
    @abstractmethod
    def toggle_text(cls, collapsed: bool, heading: str) -> str:
        """The toggle's arrows around the bar's heading."""

    @classmethod
    @abstractmethod
    def control_offset(cls, distance: int) -> Offset: ...

    @classmethod
    def opposite(cls) -> type[SidebarEdge]:
        """The other concrete edge on the same axis (left<->right, top<->bottom).

        Answered by the axis class itself (``cls.axis()._edge_by_sign``), not the
        DeclaredFamily registry. On Android we saw ``members_with(cls.axis())``
        occasionally return only ``cls`` — the registry's membership derivation
        can race with module import under python-for-android — and the resulting
        ``StopIteration`` aborts the first sidebar paint (``RuntimeError:
        coroutine raised StopIteration``). The axis's own sign table is
        populated at module end and never recomputed, so it is deterministic
        regardless of import order."""
        return cls.axis()._edge_by_sign[-cls.sign]

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
    # Populated at module end once LeftSidebarEdge and RightSidebarEdge exist;
    # read by SidebarEdge.opposite() without going through the DeclaredFamily registry.
    _edge_by_sign: ClassVar[dict[int, type[SidebarEdge]]] = {}

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
    def pack(cls, extents: Sequence[int], folds: Sequence[type[SidebarFold]], viewport: Size,
             split: int) -> tuple[SidebarGeometry, ...]:
        """Bars on a left or right edge stand next to each other, each its own column; a fold
        is already its extent."""
        return tuple(SidebarGeometry(offset, extent)
                     for offset, extent in zip(accumulate((0, *extents)), extents))

    @classmethod
    def slots[K](cls, keys: Sequence[K]) -> tuple[tuple[K, ...], ...]:
        """Each column is its own slot."""
        return tuple((key,) for key in keys)

    @classmethod
    def onward(cls) -> type[SidebarEdge]:
        """Columns stack inward from the wall, so the next one lies toward the centre."""
        return cls.opposite()

    @classmethod
    def size_toggle(cls, toggle: StyledControl) -> None:
        toggle.styles.width, toggle.styles.height = cls.collapsed_extent, "1fr"

    @classmethod
    def size_handle(cls, handle: StyledControl) -> None:
        handle.styles.width, handle.styles.height = 1, "1fr"
        handle.styles.pointer = "ew-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "\n".join("│" for _ in range(size.height))

    @classmethod
    def toggle_text(cls, collapsed: bool, heading: str) -> str:
        """A column: the arrow, the heading read downward, the arrow."""
        symbol = cls.toggle_symbol(collapsed)
        return "\n".join((symbol, "", *heading, "", symbol))

    @classmethod
    def control_offset(cls, distance: int) -> Offset:
        return Offset(-cls.sign * distance, 0)


class HeightSidebarEdge(SidebarEdge):
    minimum = 9
    conversation_minimum = 8
    collapsed_extent = 2
    # Populated at module end once TopSidebarEdge and BottomSidebarEdge exist;
    # read by SidebarEdge.opposite() without going through the DeclaredFamily registry.
    _edge_by_sign: ClassVar[dict[int, type[SidebarEdge]]] = {}

    @classmethod
    def axis(cls) -> type[SidebarEdge]:
        return HeightSidebarEdge

    @classmethod
    def extent(cls, size: Size) -> int:
        return size.height

    @classmethod
    def coordinate(cls, point: Offset) -> int:
        return point.y

    splitter = 1
    """Columns of the handle on a band's first bar that drags the split between its bars."""
    cross_minimum = WidthSidebarEdge.minimum
    """The narrowest a bar in a band gets, as wide as the narrowest left or right bar."""

    @classmethod
    def region(cls, size: Size, span: SidebarGeometry, occupied: Spacing) -> Region:
        return Region(span.cross_offset, cls.origin(size.height, span.offset, span.extent),
                      span.cross_extent, span.extent)

    @classmethod
    def pack(cls, extents: Sequence[int], folds: Sequence[type[SidebarFold]], viewport: Size,
             split: int) -> tuple[SidebarGeometry, ...]:
        """Bars on a top or bottom edge sit side by side in one band rather than stacking.
        Two open bars split the width (`split` percent for the first); a folded bar beside an
        open one rises to the open band's height as a narrow strip (`WidthSidebarEdge.collapsed_extent`)
        so tapping it opens both into the split."""
        room = max(folds, key=attrgetter("shares"), default=FoldedSidebarFold).band.of(
            folds, extents, viewport.width, lambda count, width: cls.shares(count, width, split))
        return tuple(fold.in_band(room, extent) for fold, extent in zip(folds, extents))

    @classmethod
    def shares(cls, count: int, width: int, split: int) -> tuple[int, ...]:
        """The open bars' widths: the first takes `split` percent, the rest share what remains."""
        cut = max(0, min(max(width * split // 100, cls.cross_minimum),
                         width - cls.cross_minimum * (count - 1))) if count > 1 else width
        cuts = [0, *(cut + (width - cut) * index // max(count - 1, 1) for index in range(count - 1)), width]
        return tuple(end - start for start, end in zip(cuts, cuts[1:]))[:count]

    @classmethod
    def slots[K](cls, keys: Sequence[K]) -> tuple[tuple[K, ...], ...]:
        """The band is one slot: its open bars are as tall as each other."""
        return (tuple(keys),) if keys else ()

    @classmethod
    def onward(cls) -> type[SidebarEdge]:
        """A band packs its bars left to right, so the next one lies to the right."""
        return RightSidebarEdge

    @classmethod
    def size_toggle(cls, toggle: StyledControl) -> None:
        toggle.styles.width, toggle.styles.height = "1fr", cls.collapsed_extent

    @classmethod
    def size_handle(cls, handle: StyledControl) -> None:
        handle.styles.width, handle.styles.height = "1fr", 1
        handle.styles.pointer = "ns-resize"

    @classmethod
    def handle_text(cls, size: Size) -> str:
        return "─" * size.width

    @classmethod
    def toggle_text(cls, collapsed: bool, heading: str) -> str:
        """One centered row with the edge's arrows flanking the heading (no second blank arrow row)."""
        symbol = cls.toggle_symbol(collapsed)
        return f"{symbol}  {heading}  {symbol}"

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


# Each axis owns its leading/trailing concrete edge pair here, so `opposite()` resolves
# without walking the DeclaredFamily registry (whose members_with caching we saw race with
# module import under python-for-android — see opposite()'s docstring).
WidthSidebarEdge._edge_by_sign = {LeftSidebarEdge.sign: LeftSidebarEdge,
                                  RightSidebarEdge.sign: RightSidebarEdge}
HeightSidebarEdge._edge_by_sign = {TopSidebarEdge.sign: TopSidebarEdge,
                                   BottomSidebarEdge.sign: BottomSidebarEdge}


@dataclass(frozen=True, slots=True)
class SidebarPlacement(DeclaredFamily, affix="SidebarPlacement"):
    """A nominal workspace role owns its initial policy and native spelling."""

    default_side: ClassVar[type[SidebarEdge]]
    default_extent_percent: ClassVar[int]
    scope: ClassVar[str]
    """What the bar shows when nothing it follows is open: the two bars look alike otherwise."""

    side: type[SidebarEdge]
    order: int
    extent_percent: int
    floating: bool = False

    @classmethod
    def initial(cls) -> Self:
        return cls(cls.default_side, 0, cls.default_extent_percent)

    @classmethod
    def heading(cls, viewed: Iterable[str]) -> str:
        """What the bar's toggle names, given the titles of the tabs being viewed: its scope."""
        return cls.scope

    @classmethod
    def available(cls, conversation_open: bool) -> bool:
        """Whether this sidebar role is available given whether a conversation is open."""
        return True


class ActiveSidebarPlacement(SidebarPlacement, declared_name=None):
    """The sidebar roles a current view can actually own."""


class ChannelsSidebarPlacement(ActiveSidebarPlacement):
    default_side = LeftSidebarEdge
    default_extent_percent = 40
    scope = "all"


class ThreadSidebarPlacement(ActiveSidebarPlacement):
    default_side = RightSidebarEdge
    default_extent_percent = 34
    scope = "this"

    @classmethod
    def heading(cls, viewed: Iterable[str]) -> str:
        """The bar follows the viewed tab, so it names it by the tab's own title: the DM, the
        channel or the file."""
        return next(iter(viewed), cls.scope)

    @classmethod
    def available(cls, conversation_open: bool) -> bool:
        """The thread's settings follow an open conversation."""
        return conversation_open


class ObjectSidebarPlacement(SidebarPlacement):
    """Read already-saved third-bar positions; no current view owns this role."""


@dataclass
class BandRoom(ABC):
    """One band's room while its bars take it, named by the band's most open fold."""

    width: int
    beyond: int
    """Rows the folded strips take from the wall: the shares start past them."""
    starts: Iterator[int]
    widths: Iterator[int]

    @classmethod
    def of(cls, folds: Sequence[type[SidebarFold]], extents: Sequence[int], width: int,
           shares: Callable[[int, int], tuple[int, ...]]) -> BandRoom:
        widths = shares(cls.sharing(folds), width)
        return cls(width, cls.walled(folds, extents), iter(accumulate((0, *widths))), iter(widths))

    @classmethod
    @abstractmethod
    def sharing(cls, folds: Sequence[type[SidebarFold]]) -> int:
        """How many of the band's bars divide its width."""

    @classmethod
    @abstractmethod
    def walled(cls, folds: Sequence[type[SidebarFold]], extents: Sequence[int]) -> int:
        """Rows the folded strips take from the wall."""

    def share(self, extent: int) -> SidebarGeometry:
        return SidebarGeometry(self.beyond, extent, next(self.starts), next(self.widths))

    @abstractmethod
    def strip(self, extent: int) -> SidebarGeometry:
        """Where a folded bar's toggle lies."""


@dataclass
class OpenBandRoom(BandRoom):
    """A band with an open bar: folded peers rise beside it as narrow vertical strips at the
    same band height, and open bars share the remaining width in declared order."""

    band_extent: int = 0

    @classmethod
    def of(cls, folds: Sequence[type[SidebarFold]], extents: Sequence[int], width: int,
           shares: Callable[[int, int], tuple[int, ...]]) -> BandRoom:
        folded_width = WidthSidebarEdge.collapsed_extent
        folded_count = sum(1 - fold.shares for fold in folds)
        open_width = max(0, width - folded_width * folded_count)
        open_widths = iter(shares(cls.sharing(folds), open_width))
        widths = tuple(
            next(open_widths) if fold.shares else min(folded_width, width)
            for fold in folds
        )
        band_extent = max((extent for fold, extent in zip(folds, extents) if fold.shares), default=0)
        return cls(width, 0, iter(accumulate((0, *widths))), iter(widths), band_extent=band_extent)

    @classmethod
    def sharing(cls, folds: Sequence[type[SidebarFold]]) -> int:
        return sum(fold.shares for fold in folds)

    @classmethod
    def walled(cls, folds: Sequence[type[SidebarFold]], extents: Sequence[int]) -> int:
        return 0

    def strip(self, extent: int) -> SidebarGeometry:
        return SidebarGeometry(0, self.band_extent or extent, next(self.starts), next(self.widths))


class FoldedBandRoom(BandRoom):
    """A band with no open bar: its folded toggles share the width side by side at the wall."""

    @classmethod
    def sharing(cls, folds: Sequence[type[SidebarFold]]) -> int:
        return len(folds)

    @classmethod
    def walled(cls, folds: Sequence[type[SidebarFold]], extents: Sequence[int]) -> int:
        return 0

    def strip(self, extent: int) -> SidebarGeometry:
        return self.share(extent)


class SidebarFold(DeclaredFamily, affix="SidebarFold"):
    """A bar open to its extent or folded to its toggle, as a shared band divides its width."""

    shares: ClassVar[int]
    """How many shares of a band's width the bar takes."""
    band: ClassVar[type[BandRoom]]
    """The room a band takes when this is its most open fold."""

    @classmethod
    @abstractmethod
    def in_band(cls, room: BandRoom, extent: int) -> SidebarGeometry:
        """Where the bar lies in a band its neighbours share."""

    @classmethod
    def of(cls, collapsed: bool) -> type[SidebarFold]:
        """The fold a widget's collapsed reactive names, read once at the layout boundary."""
        return FoldedSidebarFold if collapsed else OpenSidebarFold


class OpenSidebarFold(SidebarFold):
    """An open bar takes its share of the band's width, beside the folded strips."""

    shares = 1
    band = OpenBandRoom

    @classmethod
    def in_band(cls, room: BandRoom, extent: int) -> SidebarGeometry:
        return room.share(extent)


class FoldedSidebarFold(SidebarFold):
    """A folded bar takes no share: its toggle is a strip where the band's room puts it."""

    shares = 0
    band = FoldedBandRoom

    @classmethod
    def in_band(cls, room: BandRoom, extent: int) -> SidebarGeometry:
        return room.strip(extent)


@dataclass(frozen=True)
class BandSplit:
    """How the top or bottom band on one edge divides its width between its bars."""

    side: type[SidebarEdge]
    percent: int = 50
    """The first bar's share of the band's width."""


@dataclass(frozen=True, slots=True)
class SidebarGeometry:
    offset: int
    extent: int
    cross_offset: int = 0
    """Where a bar sharing a top or bottom band starts across it; left and right bars span the free height."""
    cross_extent: int = 0
