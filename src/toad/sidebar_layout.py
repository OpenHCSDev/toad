"""One app-owned placement policy for independently movable sidebar surfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar, Protocol

from agent_comms.nominal.declared_family import DeclaredFamily
from metaclass_registry import AbstractHooksMeta
from textual.geometry import Offset, Region, Size, Spacing

from toad.sidebar_placement import (
    ActiveSidebarPlacement,
    ChannelsSidebarPlacement,
    BandSplit,
    SidebarEdge,
    SidebarFold,
    SidebarGeometry,
    SidebarPlacement,
)
from toad.client.sidebar_panels import PanelSpec
from toad.terminal_origin import TerminalLayout, TerminalOrigin

if TYPE_CHECKING:
    from toad.client.application import ClientApplication


class PlacementControl(metaclass=AbstractHooksMeta):
    """One sidebar placement control as a frontend draws it — a Textual Static, a Qt button.
    It holds the action it stands for, and the SidebarPlacementAction family presents it
    through these three calls, so an arrow or Float reads the same whichever toolkit holds it."""

    action: SidebarPlacementAction

    @abstractmethod
    def set_shown(self, shown: bool) -> None:
        """Show or hide the control."""

    @abstractmethod
    def set_label(self, label: str) -> None:
        """The control's text."""

    @abstractmethod
    def set_tooltip(self, tooltip: str) -> None:
        """The control's hover text."""


class ArrangementStore(Protocol):
    """Where a terminal's saved sidebar arrangement lives. The one Toad setting owns it on
    the desktop (SavedSettings over toad.json); a frontend that keeps no settings file holds
    the arrangement for its own session. SidebarLayout reads and writes only through this, so
    the move and float policy is the one owner over whichever store a frontend brings."""

    def current_terminals(self) -> tuple[TerminalLayout, ...]:
        """Every terminal origin's saved arrangement."""

    def store_terminals(self, terminals: tuple[TerminalLayout, ...]) -> None:
        """Replace the saved arrangements; the store decides whether and when to persist."""


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
    def present(self, control: PlacementControl, placement: SidebarPlacement,
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

    def present(self, control: PlacementControl, placement: SidebarPlacement,
                directions: dict[type[SidebarEdge], SidebarShift]) -> None:
        action = directions[self.direction]
        control.set_shown(action.available)
        control.set_tooltip(action.tooltip(self.direction))


class FloatSidebarPlacementAction(SidebarPlacementAction):
    @property
    def label(self) -> str:
        return "Float"

    def apply(self, layout: SidebarLayout, identity: type[SidebarPlacement]) -> None:
        layout.float_mode(identity)

    def present(self, control: PlacementControl, placement: SidebarPlacement,
                directions: dict[type[SidebarEdge], SidebarShift]) -> None:
        control.set_label("Push" if placement.floating else "Float")
        control.set_tooltip("Push conversation text" if placement.floating
                            else "Float over conversation text")


class SidebarControlsOwner:
    """A sidebar's pane shows one placement control per SidebarPlacementAction. The Textual
    sidebar and the Qt pane both inherit this: both build their controls from the one family
    and present them from the one layout, so their arrows and Float cannot drift apart. The
    frontend owns the control widgets (Textual mounts and queries them, Qt keeps a list); this
    owns only which actions exist and how the family draws each."""

    @staticmethod
    def placement_actions() -> Iterator[SidebarPlacementAction]:
        """Every placement control a sidebar offers, in the family's order."""
        for kind in SidebarPlacementAction.members_with(SidebarPlacementAction):
            yield from kind.offered()

    @staticmethod
    def present_placement_controls(controls: Iterator[PlacementControl], layout: SidebarLayout,
                                   identity: type[SidebarPlacement]) -> None:
        """Draw each control from the one layout: the same placement and the same directions
        decide each arrow's reach and Float's label for both frontends."""
        placement = layout.get(identity)
        directions = layout.directions(identity)
        for control in controls:
            control.action.present(control, placement, directions)


class SidebarSurface(SidebarControlsOwner, metaclass=AbstractHooksMeta):
    """One sidebar as a frontend presents it: Textual's SideBar and Qt's QtSideBar both
    inherit this. A surface names its placement role and whether it is folded to its toggle;
    the chrome arrangement reads only these two to place it, and the surface's own parts
    (toggle strip, resize handle, content) sit where its edge's owners put them."""

    @property
    @abstractmethod
    def placement_identity(self) -> type[SidebarPlacement]:
        """The placement role this surface draws."""

    @property
    @abstractmethod
    def collapsed(self) -> bool:
        """Whether the surface shows only its toggle strip."""

    @property
    @abstractmethod
    def sidebar_layout(self) -> SidebarLayout:
        """The one placement owner this surface's controls write."""

    @property
    @abstractmethod
    def client(self) -> ClientApplication:
        """The application whose settings keep this surface's arrangement."""

    @abstractmethod
    def lay_out(self) -> None:
        """Lay the workspace out again from the layout's placements."""

    def arranged(self) -> None:
        """The placement changed: the workspace is laid out again, and the arrangement is
        kept in the settings file now, for the next start of any frontend."""
        self.lay_out()
        self.client.keep_settings()

    @abstractmethod
    def toggle_controls(self) -> None:
        """Show or hide the extent slider and placement actions."""

    @abstractmethod
    def fold(self, collapsed: bool) -> None:
        """Fold the surface to its strip (True) or open its pane (False), through the
        frontend's one collapsed owner, and lay the workspace out again."""

    def toggle_pane(self) -> None:
        """A click on the strip: open a folded pane, fold an open one."""
        self.fold(not self.collapsed)

    controls_wanted = True
    """Whether the reader shows the extent slider and placement actions (`toggle_controls`);
    they are hidden while the surface holds the window alone, and come back as the reader
    left them."""

    @property
    def holds_alone(self) -> bool:
        """This surface takes the whole window (`SidebarLayout.holds_alone`)."""
        return self.sidebar_layout.holds_alone(self.placement_identity)

    def content_padding(self) -> Spacing:
        """The room the content leaves its strip and grip: none while it holds the window."""
        return Spacing() if self.holds_alone else self.placement.side.content_padding()

    @property
    def placement(self) -> SidebarPlacement:
        return self.sidebar_layout.get(self.placement_identity)

    def resize_to(self, percentage: int) -> None:
        """The extent slider or resize handle asks for a new extent."""
        if self.sidebar_layout.resize(self.placement_identity, percentage):
            self.arranged()

    def apply_placement_action(self, action: SidebarPlacementAction) -> None:
        """An arrow or Float pressed: the action applies to the one layout."""
        action.apply(self.sidebar_layout, self.placement_identity)
        self.arranged()

    def present_extent_track(self, track: SidebarExtentTrack) -> None:
        """The extent slider reads this placement's extent, reversed on a trailing edge."""
        placement = self.placement
        track.reversed = placement.side.sign < 0
        track.set_range(track.floor, SidebarLayout.maximum_percent, placement.extent_percent)

    def extent_dragged(self, percent: int) -> None:
        """A grip or the extent slider is held at ``percent``. Below the fold threshold the
        pane keeps its smallest extent (it folds when released there); from it upward the
        pane opens if folded and takes the extent. One rule for every grip on every frontend.
        A hold only lays the bars out: nothing reaches the settings until it ends."""
        if percent >= SidebarLayout.fold_percent:
            if self.collapsed:
                self.fold(False)
            if self.sidebar_layout.hold(self.placement_identity, percent):
                self.lay_out()

    def extent_released(self, percent: int, restore: int) -> None:
        """The hold ends at ``percent``. Kept, the held extent is written once and the
        conversation takes its new room. Released below the fold threshold the pane folds
        instead, and keeps ``restore``, what it had before this hold, so a click on the strip
        reopens it there."""
        layout = self.sidebar_layout
        if percent >= SidebarLayout.fold_percent:
            if layout.keep_held():
                self.arranged()
            return
        layout.drop_held()
        layout.resize(self.placement_identity, restore)
        if self.collapsed:
            self.arranged()
        else:
            self.fold(True)
            self.client.keep_settings()

    def dragged_percent(self, start_percent: int, delta: Offset, viewport_extent: int) -> int:
        """The extent a resize-handle drag of ``delta`` asks for, from ``start_percent``,
        across a workspace ``viewport_extent`` long on the placement's axis."""
        edge = self.placement.side
        return start_percent + round(100 * edge.sign * edge.coordinate(delta) / max(1, viewport_extent))

    def surface_parts(self, size: Size) -> SurfaceParts:
        """Where this surface's toggle strip, resize handle and content go inside its own
        region, in cells. Both sit on the conversation-facing side (the edge's opposite), as
        Textual docks SideBarToggle and SidebarResizeHandle; the content keeps
        `content_padding` clear of them. Holding the window alone, the content is all of it."""
        edge = self.placement.side
        inner = edge.opposite()
        cross = size.width
        toggle = inner.region(size, SidebarGeometry(0, edge.collapsed_extent, 0, cross), Spacing())
        handle = inner.region(size, SidebarGeometry(edge.collapsed_extent, 1, 0, cross), Spacing())
        content = Region(0, 0, size.width, size.height).shrink(self.content_padding())
        return SurfaceParts(toggle, handle, content)


class SidebarResizeGrip(metaclass=AbstractHooksMeta):
    """The line between a sidebar's content and its toggle strip: Textual's
    `SidebarResizeHandle` and Qt's `QtSidebarResizeHandle` both inherit this. A drag resizes
    the sidebar from the extent it had when the drag began; a press without a drag shows or
    hides the slider and placement actions."""

    grip_tooltip = "Drag to resize; drag to the edge to fold"

    @property
    @abstractmethod
    def grip_surface(self) -> SidebarSurface:
        """The sidebar this grip resizes."""

    @abstractmethod
    def grip_viewport_extent(self) -> int:
        """The workspace's length on the sidebar's axis, in the units drags arrive in."""

    def begin_grip(self) -> None:
        """A press: the pane's extent now is what a fold on release restores. A folded pane is
        held from nothing, so dragging its strip outward opens it as far as the pointer goes."""
        surface = self.grip_surface
        self._grip_restore = surface.placement.extent_percent
        self._grip_start = 0 if surface.collapsed else self._grip_restore
        self._grip_percent = self._grip_start

    def drag_grip(self, delta: Offset) -> None:
        surface = self.grip_surface
        self._grip_percent = surface.dragged_percent(self._grip_start, delta, self.grip_viewport_extent())
        surface.extent_dragged(self._grip_percent)

    def end_grip(self) -> None:
        """A drag let go: released at the wall the pane folds and keeps its pre-drag extent."""
        self.grip_surface.extent_released(self._grip_percent, self._grip_restore)

    def grip_clicked(self) -> None:
        self.grip_surface.toggle_controls()


class SidebarFoldGrip(SidebarResizeGrip):
    """The pane's strip, as both frontends' toggles inherit it: a drag resizes exactly as the
    resize handle does (opening a folded pane, folding at the wall), and a click without a
    drag opens or folds the pane."""

    grip_tooltip = "Click to show or hide; drag to resize"

    def grip_clicked(self) -> None:
        self.grip_surface.toggle_pane()


@dataclass(frozen=True, slots=True)
class PlacedSidebar:
    """Where the chrome arrangement last put one sidebar, in cells, and whether it was folded
    there: comparing two of these says whether the bar just opened or folded."""

    region: Region
    folded: bool


@dataclass(frozen=True, slots=True)
class SurfaceParts:
    toggle: Region
    handle: Region
    content: Region


class SidebarToggleFace(metaclass=AbstractHooksMeta):
    """A sidebar's toggle strip as a frontend draws it — Textual's SideBarToggle, Qt's
    QtSideBarToggle. The edge owns the strip's text (its arrows around the heading); the
    face only shows what this computes, so the two frontends' strips read the same."""

    @abstractmethod
    def show_toggle(self, text: str, tooltip: str) -> None:
        """Draw the strip's text and hover text."""

    def present_toggle(self, collapsed: bool, edge: type[SidebarEdge], heading: str) -> None:
        self.show_toggle(edge.toggle_text(collapsed, heading),
                         "Expand sidebar" if collapsed else "Collapse sidebar")


class SidebarExtentTrack:
    """The extent slider's value and the track it draws: Textual's SidebarSlider and Qt's
    QtSidebarSlider both inherit it, so the percentage, the thumb's cell and the value a
    pointer at one cell picks are owned once. A trailing-edge sidebar reverses the track so
    its thumb moves the way its wall-facing edge does."""

    label_cells = 4
    # The track's wall end: held there and let go, the pane folds.
    floor = 0

    def start_track(self, minimum: int, maximum: int, value: int) -> None:
        """Each frontend's constructor calls this once beside its own widget's."""
        self.minimum = minimum
        self.maximum = maximum
        self.value = value
        self.reversed = False

    @property
    def track_tooltip(self) -> str:
        return (f"Drag or use ←/→ to resize (up to {self.maximum}% of the placement axis); "
                "let go at 0 to fold")

    def set_range(self, minimum: int, maximum: int, value: int) -> None:
        self.minimum, self.maximum = minimum, max(minimum, maximum)
        self.value = max(self.minimum, min(self.maximum, value))

    def track_text(self, width: int) -> str:
        """The track ``width`` cells wide: the percentage, then a line with the thumb."""
        label = f"{self.value:2d}%"
        track = max(1, width - len(label) - 1)
        ratio = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        if self.reversed:
            ratio = 1 - ratio
        thumb = round(ratio * (track - 1))
        line = "".join("●" if index == thumb else "─" for index in range(track))
        return f"{line} {label}" if self.reversed else f"{label} {line}"

    def value_at(self, x: int, width: int, reverse: bool) -> int:
        """The value a pointer ``x`` cells into a ``width``-cell track picks."""
        label_width = 0 if reverse else self.label_cells
        track = max(1, width - self.label_cells)
        ratio = max(0.0, min(1.0, (x - label_width) / max(1, track - 1)))
        if reverse:
            ratio = 1 - ratio
        return round(self.minimum + ratio * (self.maximum - self.minimum))

    def begin_track(self, surface: SidebarSurface) -> None:
        """A press on the track: the extent now is what a fold on release restores."""
        self._track_restore = surface.placement.extent_percent

    def track_moved(self, surface: SidebarSurface, value: int) -> None:
        if value != self.value:
            self.value = value
            surface.extent_dragged(value)

    def track_released(self, surface: SidebarSurface) -> None:
        surface.extent_released(self.value, self._track_restore)

    def stepped(self, direction: int) -> int:
        if self.reversed:
            direction = -direction
        return max(self.minimum, min(self.maximum, self.value + direction))


CHANNELS_PANEL = PanelSpec(title="Channels", flex=True)
"""The Channels sidebar's one panel: the channel groups with their threads nested under
each. Textual's ChannelsSidebar and Qt's channels surface both declare exactly this."""


@dataclass(frozen=True, slots=True)
class ChromeArrangement[Bar]:
    content: Region
    """The conversation's region: the viewport less every pushing sidebar's gutter."""
    gutter: Spacing
    bars: dict[Bar, Region]
    """Each presented sidebar's region; a floating one overlays the content."""


class SidebarChromeArrangement[Bar: SidebarSurface](ABC):
    """Where the conversation and each presented sidebar go in one viewport, in cells. Textual's
    WorkspaceChrome and Qt's QtWorkspaceChrome both inherit this, so at any viewport the two
    frontends dock, push and float the same sidebars in the same regions: the one
    SidebarLayout resolves them."""

    @property
    @abstractmethod
    def sidebar_layout(self) -> SidebarLayout: ...

    @abstractmethod
    def presented_sidebars(self) -> tuple[Bar, ...]: ...

    def arrange_chrome(self, viewport: Size) -> ChromeArrangement[Bar]:
        bars = self.presented_sidebars()
        layout = self.sidebar_layout
        # No tab shown: the sole bar is the whole window and nothing else is placed.
        for bar in bars:
            if layout.holds_alone(bar.placement_identity):
                return ChromeArrangement(Region(viewport.width, 0, 0, viewport.height),
                                         Spacing(left=viewport.width),
                                         {bar: Region(0, 0, viewport.width, viewport.height)})
        collapsed = {bar.placement_identity: bar.collapsed for bar in bars}
        resolved = layout.resolve(viewport, collapsed)
        # While a grip holds an extent the bars follow it, but the conversation keeps the room
        # the kept arrangement gives it: it is laid out (its rows measured) once, on release.
        gutter = layout.resolve(viewport, collapsed, resting=True).gutter if layout.holding else resolved.gutter
        content = Region(gutter.left, gutter.top, max(0, viewport.width - gutter.width),
                         max(0, viewport.height - gutter.height))
        return ChromeArrangement(content, gutter,
                                 {bar: resolved.bars[bar.placement_identity] for bar in bars})


@dataclass(frozen=True, slots=True)
class ResolvedSidebarLayout:
    bars: dict[type[SidebarPlacement], Region]
    gutter: Spacing


class SidebarLayout:
    """Placement policy over the arrangement saved for this terminal origin.

    The settings own the placements: each role's saved record, or the role's
    own initial placement until the user moves or resizes it.

    Owns per-identity collapsed state too: each SidebarPlacement is either
    collapsed (bar visible, pane hidden) or open (bar visible, pane expanded).
    Frontends read `is_collapsed` / write `set_collapsed` / `toggle_collapsed`
    through this one owner — no parallel ``_pane_open`` dict on Qt or
    ``SideBar.collapsed`` reactive on Textual answering the same question twice.
    Default is collapsed (True) until something opens the pane; a pane that is
    not currently available (e.g. the thread settings on the welcome tab) is
    always treated collapsed regardless of its stored state.
    """

    minimum_percent = 15
    maximum_percent = 50
    sole_role: ClassVar[type[SidebarPlacement]] = ChannelsSidebarPlacement
    """The bar that takes the whole window while no tab is shown: the comms sidebar (its
    channels, threads, search and buses), with Toad's banner at its head. It replaced the
    welcome page (Tristan, 2026-11-18): opening a row gives the first tab, and the bar
    returns to its kept placement beside it, with the other bars the view brings."""
    # A grip or the slider held below this folds the pane when released.
    fold_percent = minimum_percent // 2

    def __init__(self, settings: ArrangementStore, origin: type[TerminalOrigin],
                 alone: Callable[[], bool] = lambda: False) -> None:
        self.settings, self.origin = settings, origin
        # Whether no tab is shown: the application answers it from the selected view (the
        # welcome mode is the one view that is not a tab), so nothing here keeps a copy.
        self._alone = alone
        self._collapsed: dict[type[SidebarPlacement], bool] = {}
        # Extents a grip is holding: the bars are drawn at them, but nothing is written to the
        # settings until the hold ends (`keep_held`), so a drag costs only its layout.
        self._held: dict[type[SidebarPlacement], int] = {}

    @property
    def alone(self) -> bool:
        """No tab is shown: the `sole_role` bar holds the window."""
        return self._alone()

    def holds_alone(self, identity: type[SidebarPlacement]) -> bool:
        """Whether ``identity``'s bar takes the whole window: no tab is shown and it is the
        `sole_role`. Such a bar is open whatever its kept fold, and shows no strip, grip or
        placement controls: there is nothing beside it to make room for."""
        return identity is self.sole_role and self.alone

    def kept_collapsed(self, identity: type[SidebarPlacement]) -> bool:
        """The fold kept for ``identity``: True (only its toggle) until something opens it.
        `set_collapsed` and `toggle_collapsed` read and write this one, never the open state a
        bar holding the window alone shows over it."""
        return self._collapsed.get(identity, True)

    def is_collapsed(self, identity: type[SidebarPlacement]) -> bool:
        """Whether the bar for ``identity`` shows only its toggle (True) or its
        expanded pane too (False): its kept fold, except that a bar holding the window
        alone is open; its kept fold returns with the first tab."""
        return not self.holds_alone(identity) and self.kept_collapsed(identity)

    def set_collapsed(self, identity: type[SidebarPlacement], value: bool) -> bool:
        """Keep ``identity``'s fold; returns whether what the bar shows changed."""
        shown = self.is_collapsed(identity)
        self._collapsed[identity] = value
        return self.is_collapsed(identity) != shown

    def toggle_collapsed(self, identity: type[SidebarPlacement]) -> bool:
        """Flip ``identity``'s kept fold; returns the new value."""
        new_value = not self.kept_collapsed(identity)
        self._collapsed[identity] = new_value
        return new_value

    def collapsed_map(self) -> dict[type[SidebarPlacement], bool]:
        """Every placement's collapsed state in one dict, as `resolve` reads it. A role
        the layout has never seen is collapsed (its default). Includes every active role,
        so pack/share logic can iterate the whole set in one pass."""
        return {role: self.is_collapsed(role) for role in self.placements}

    @property
    def terminal(self) -> TerminalLayout:
        """This origin's saved arrangement, or an empty one until something is saved."""
        saved = (terminal for terminal in self.settings.current_terminals()
                 if terminal.origin is self.origin)
        return next(saved, TerminalLayout(self.origin))

    @property
    def resting_placements(self) -> dict[type[SidebarPlacement], SidebarPlacement]:
        """The kept arrangement: the settings' placements, or each role's initial one."""
        saved = {type(placement): placement for placement in self.terminal.placements}
        return {role: saved.get(role, role.initial()) for role in ActiveSidebarPlacement.members_with(ActiveSidebarPlacement)}

    @property
    def placements(self) -> dict[type[SidebarPlacement], SidebarPlacement]:
        """The arrangement as drawn now: the kept one, with any extent a grip is holding."""
        placements = self.resting_placements
        for role, percent in self._held.items():
            placements[role] = replace(placements[role], extent_percent=percent)
        return placements

    @property
    def holding(self) -> bool:
        return bool(self._held)

    def hold(self, identity: type[SidebarPlacement], percentage: int) -> bool:
        """A grip holds ``identity``'s slot at ``percentage``: drawn so, not yet kept."""
        placements = self.placements
        percentage = max(self.minimum_percent, min(self.maximum_percent, percentage))
        slot = self._slot(placements, identity)
        if all(placements[key].extent_percent == percentage for key in slot):
            return False
        for key in slot:
            self._held[key] = percentage
        return True

    def keep_held(self) -> bool:
        """The hold ended: write the held extents to the settings once."""
        if not self._held:
            return False
        placements = self.placements
        self._held.clear()
        self._store(placements)
        return True

    def drop_held(self) -> None:
        """The hold ended without keeping what it held (the pane folded instead)."""
        self._held.clear()

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
        """Whether the next shown bar in this one's band sits beside it, so its splitter shows:
        bars whose folds take equal shares share a row; a folded strip under an open bar does
        not. `collapsed` holds the shown bars, as `resolve` reads it; a hidden bar has none."""
        shown = tuple(key for key in self._slot(self.placements, identity) if key in collapsed)
        index = shown.index(identity)
        return any(SidebarFold.of(collapsed[identity]).shares == SidebarFold.of(collapsed[after]).shares
                   for after in shown[index + 1:index + 2])

    def _store(self, placements: dict[type[SidebarPlacement], SidebarPlacement]) -> None:
        self._save(replace(self.terminal, placements=tuple(placements.values())))

    def _save(self, terminal: TerminalLayout) -> None:
        others = tuple(saved for saved in self.settings.current_terminals()
                       if saved.origin is not self.origin)
        self.settings.store_terminals((*others, terminal))

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

    def resolve(self, viewport: Size, collapsed: dict[type[SidebarPlacement], bool], *,
                resting: bool = False) -> ResolvedSidebarLayout:
        """Pack each axis once; top/bottom surfaces own the corners.

        Float changes only conversation clearance. A pushed inner peer clears
        its floating outer peer too; collapsed handles always reserve space.
        """
        placements = self.resting_placements if resting else self.placements
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
