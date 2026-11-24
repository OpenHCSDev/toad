from __future__ import annotations
from abc import abstractmethod

from functools import cached_property

from agent_comms.cli_support.cli_failures import CLI_FAILURES
from formbridge.key_declarations import TextEntryMode
from textual._callback import invoke

from metaclass_registry.mro_dispatch import handles
from toad.client.tab_order import TabOrder
from toad.core_event_carrier import CoreEventReceiver
from toad.settings_scope import ViewSettingsScope
from toad.worker_group import WorkerGroup
from toad.core import events as core_events
from textual.content import Content
from toad.client.application_actions import ApplicationAction
from toad.widget_actions import ActivationKeys, Activates, DismissibleControl, WidgetAction, DeclaredWidgetActions, StepsHorizontalCursor, StepsVerticalCursor, VisibleActions

from toad.widgets.comms_menu import ContextMenu
from toad.core.preference_events import PreferenceChanged
from toad.client.sidebar_filter import SidebarFilter
from toad.client.sidebar_panels import PanelSpec
from toad.preferences import SETTINGS
from dataclasses import dataclass
from agent_comms.nominal.declared_family import DeclaredFamily
from typing import TYPE_CHECKING, ClassVar

from textual import containers, events, on, widgets
from textual.app import ComposeResult
from textual.events import Click
from textual.geometry import Offset
from textual.message import Message
from textual.reactive import reactive
from textual._activation import PrimaryActivation
from textual.css.native import DeclaresTheme, Keyword, NativeDeclaration, Percent, Variable
from textual.css.styles import Styles
from textual.widget import Widget

from ui_theme.scheme import SidebarToneColour, AccentColour, ForegroundColour, PrimaryColour, SuccessColour

from toad.core.projection import MroProjection
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    Bold,
    CenteredContent,
    FillHeight,
    FillWidth,
    HiddenOverflow,
    MutedText,
    NoMargin,
    NoPadding,
    OneRow,
    PointerCursor,
    SidePadding,
)

from toad.workspace_frame import WorkspaceHosted
from toad.tone_paint import TonePaint
from toad.widgets.selection import HoverSelection, ColourSelection
from toad.client.session_tracker import SidebarState
from toad.client.sidebar_filter import SidebarSearchField
from toad.client.sidebar_panels import PanelMenuModel, SidebarPanelCollapse
from toad.thread_sidebar_declarations import ThreadSidebarContents
from toad.sidebar_layout import (
    DirectionalSidebarPlacementAction,
    FloatSidebarPlacementAction,
    PlacementControl,
    SidebarExtentTrack,
    SidebarLayout,
    SidebarPlacementAction,
    SidebarFoldGrip,
    SidebarResizeGrip,
    SidebarShift,
    SidebarSurface,
    SidebarToggleFace,
)
from toad.pointer_gesture import NO_GESTURE, Gesture, GestureControl, PressedGesture
from toad.sidebar_placement import HeightSidebarEdge, SidebarEdge, SidebarPlacement, ThreadSidebarPlacement
from toad.widgets.sidebar_viewport import SidebarViewport, ViewportHeader
from toad.app_node import ToadNode

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class BarPresentation:
    side: type[SidebarEdge]
    order: int
    floating: bool
    collapsed: bool
    directions: tuple[type[SidebarShift], ...]
    leads_band: bool
    """The next bar in its band sits beside this one, so this bar carries the splitter."""

    @classmethod
    def from_placement(
        cls,
        placement: SidebarPlacement,
        *,
        collapsed: bool,
        directions: dict[type[SidebarEdge], SidebarShift],
        leads_band: bool,
    ) -> BarPresentation:
        return cls(
            placement.side,
            placement.order,
            placement.floating,
            collapsed,
            tuple(type(action) for action in directions.values()),
            leads_band,
        )


class PanelHydration(WorkerGroup):
    """Loads a sidebar's panels once it is shown; leaving the view cancels it."""


class SidebarPanels(DeclaredFamily, affix="Panels"):
    """How far a sidebar's panels are mounted. One state, so "loading" and "loaded" can't both be true."""

    loaded: ClassVar[bool] = False

    def schedule(self, bar: SideBar) -> None:
        """Panels already loaded or on their way need no second load."""

    def start(self, bar: SideBar) -> None:
        """Panels already loaded or loading are not started again."""


class AbsentPanels(SidebarPanels):
    """Nothing is mounted: the sidebar has not been shown, or eviction released it."""

    def schedule(self, bar: SideBar) -> None:
        bar.panel_state = ScheduledPanels()
        bar.screen.frame_presentation.defer(bar, bar._start_hydration)

    def start(self, bar: SideBar) -> None:
        ScheduledPanels().start(bar)


class ScheduledPanels(SidebarPanels):
    """The load waits for the sidebar's frame to be written."""

    def start(self, bar: SideBar) -> None:
        if bar.wants_panels:
            bar.panel_state = HydratingPanels()
            PanelHydration.run_on(bar, bar._hydrate_panels())
        else:
            bar.panel_state = AbsentPanels()


class HydratingPanels(SidebarPanels):
    """Panels and controls are being mounted. Only leaving the view stops it, and eviction then discards the partial mount."""


class LoadedPanels(SidebarPanels):
    """Every panel and control is mounted."""

    loaded = True

class BarDisplay:
    """Whether native controls already show a requested sidebar projection."""

    def matches(self, current: PresentedBar) -> bool:
        return False

    def controls_changed(self, current: PresentedBar) -> bool:
        return True


@dataclass(frozen=True)
class PresentedBar(BarDisplay):
    presentation: BarPresentation
    extent_percent: int

    def matches(self, current: PresentedBar) -> bool:
        return self == current

    def controls_changed(self, current: PresentedBar) -> bool:
        return self.presentation != current.presentation




class SidebarPanelHost(Widget):
    """A panel's actual host owns whether its content is presented."""

    @property
    def panel_visible(self):
        return self.is_attached and all(node.display for node in self.walk_ancestors(with_self=True)
                                        if isinstance(node, Widget))

    @abstractmethod
    def reveal(self): ...


class SidebarPanelWidget(Widget):
    """Every sidebar panel accepts visibility changes; passive panels do nothing."""

    @property
    def panel_identity(self):
        """The nominal widget role identifies a panel across its lazy realizations."""
        return type(self)

    def finish(self) -> None:
        """Passive panels have no pending edit to submit."""

    def sidebar_visibility_changed(self) -> None:
        pass


class SidebarVisibilityObserver(SidebarPanelWidget):
    """A panel whose viewport and active presentation belong to its enclosing sidebar."""

    @property
    def panel_visible(self):
        return self.query_ancestor(SidebarPanelHost).panel_visible

    @property
    def scroll_container(self) -> SidebarViewport:
        return self.query_ancestor(SideBar).panels_viewport

    def preserve_reader(self, placements) -> None:
        self.scroll_container.preserve_reader(placements)


class SidebarPanelContents(AutoHeight, NoPadding, widgets.Collapsible.Contents):
    """A panel's contents, sized by what it holds and hidden while collapsed."""



class SideBarCollapsible(
    SidebarPanelCollapse,
    SidebarPanelHost,
    FillWidth,
    AutoHeight,
    NoPadding,
    NoMargin,
    widgets.Collapsible,
    inherit_css=False,
):
    # Selection is drawn on the focused row. Inheriting Collapsible's container
    # focus-within tint would restyle the entire channel tree on pointer entry.
    BINDING_GROUP_TITLE = "Sidebar collapsible"
    HELP = """\
## Sidebar

This is your sidebar.

The Sidebar contains additonal information associated with the conversation.

- **tab / shift+tab** Navigate sections
- **enter** expand or collapse secions
"""

    Contents = SidebarPanelContents
    expanded_min_height = 1
    """Rows an open panel keeps; a collapsed panel is its one title row."""

    @property
    def panel_visible(self):
        return super().panel_visible and not self.collapsed

    def reveal(self):
        self.collapsed = False

    def __init__(
        self, *children: Widget, header_control: Widget | None = None, **kwargs
    ):
        super().__init__(*children, **kwargs)
        self.header_control = header_control

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self._title.styles.width = "1fr"
        self._title.styles.padding = 0

    @cached_property
    def contents(self) -> SidebarPanelContents:
        return self.Contents()

    def _update_collapsed(self, collapsed: bool) -> None:
        super()._update_collapsed(collapsed)
        # Native collapse is the one fact; the contents and extent follow it.
        self.contents.display = not collapsed
        self.styles.min_height = 1 if collapsed else self.expanded_min_height

    @property
    def panel_title(self) -> str:
        return str(self.title)

    @property
    def panel_state(self) -> SidebarState:
        return self.query_ancestor(SideBar).navigation

    def watch_collapsed(self, collapsed: bool) -> None:
        if self.is_attached:
            self.record_collapsed(collapsed)

    def compose(self) -> ComposeResult:
        if self.header_control is None:
            yield self._title
        else:
            with ViewportHeader():
                yield self._title
                yield self.header_control
        with self.contents:
            yield from self._contents_list


class FlexSideBarCollapsible(SideBarCollapsible):
    """A panel whose open contents keep room to grow into."""

    expanded_min_height = 12


class ToggleSidebarAction(WidgetAction):
    """Toggle the sidebar and focus its contents."""
    keys = {TextEntryMode: ("enter", "space")}

    def apply(self, context: SideBarToggle) -> None:
        context.post_message(context.Pressed())


class HeaderButtonLook(DeclaresTheme):
    """An available header control: full ink and a pointing hand."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.color, Variable(ForegroundColour.name)),
        NativeDeclaration.of(Styles.pointer, Keyword("pointer")),
    )


class DisabledHeaderButtonLook(HeaderButtonLook):
    """A control Textual has disabled fades and stops offering the hand."""

    native_theme = (
        NativeDeclaration.of(Styles.color, Variable(ForegroundColour.name), Percent(38)),
        NativeDeclaration.of(Styles.pointer, Keyword("default")),
    )


class HeaderButton(
    CenteredContent,
    Bold,
    ActivationKeys,
    HoverSelection,
    widgets.Static,
    can_focus=True,
):
    """One compact, keyboard-accessible control in the top bar, on the bar's own tone."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 5
        self.styles.height = 3

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        # Textual's own `disabled` restyles the node; its look follows that one fact.
        look = (HeaderButtonLook, DisabledHeaderButtonLook)[self.is_disabled]
        return (*super().native_declarations(), *look.declared_theme())

class TabHistoryButton(HeaderButton):
    """Back or forward through visited tabs."""

    direction: ClassVar[int]
    label: ClassVar[str]
    available_tooltip: ClassVar[str]
    unavailable_tooltip: ClassVar[str]

    def __init__(self) -> None:
        super().__init__(self.label)
        self.tooltip = self.available_tooltip

    def sync(self, tab_order: TabOrder) -> None:
        unavailable = tab_order.history_target(self.direction) is None
        self.disabled = unavailable
        self.tooltip = (
            self.unavailable_tooltip if unavailable else self.available_tooltip
        )

    @property
    def primary_activation(self):
        return self.navigate

    def navigate(self) -> None:
        self.app.tab_order.navigate(self.direction)


class BackTabButton(TabHistoryButton):
    direction = -1
    label = "<──"
    available_tooltip = "Back through visited tabs"
    unavailable_tooltip = "No earlier visited tab"


class ForwardTabButton(TabHistoryButton):
    direction = +1
    label = "──>"
    available_tooltip = "Forward through visited tabs"
    unavailable_tooltip = "No later visited tab"


class MainMenuButton(HeaderButton):
    """Own the declared application menu and its full-height hamburger."""

    def __init__(self) -> None:
        super().__init__()
        self.tooltip = "Main menu"

    def render(self):
        return Content(
            "\n".join(
                "━" * self.content_size.width for _ in range(self.content_size.height)
            )
        )

    @property
    def primary_activation(self):
        return self.open_menu

    def open_menu(self) -> None:
        ContextMenu.show(
            self.screen,
            self.region,
            "Toad",
            ApplicationAction.menu(self.app),
            callback=self.chosen,
        )

    async def chosen(self, action: ApplicationAction | None) -> None:
        if action is not None:
            await invoke(action.apply, self.app)


class TabHistoryControls(
    AutoWidth,
    NoMargin,
    CoreEventReceiver,
    containers.HorizontalGroup,
    ToadNode,
):
    """Left-sidebar controls shared by native thread and channel screens."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.height = 3

    def compose(self) -> ComposeResult:
        yield MainMenuButton()
        yield BackTabButton()
        yield ForwardTabButton()

    @on(events.Mount)
    def on_mount(self) -> None:
        app = self.app
        self.observe_core(app.tab_order.events)
        self.observe_core(app.events)
        self._sync()

    @handles(core_events.TabHistoryChanged, core_events.OpenTabsChanged)
    async def history_changed(self, event: core_events.TabHistoryChanged | core_events.OpenTabsChanged) -> None:
        self._sync()

    def _sync(self) -> None:
        app = self.app
        for button in self.query(TabHistoryButton):
            button.sync(app.tab_order)


class CapturedDrag(GestureControl):
    """One captured pointer gesture in a terminal; controls own its coordinate mapping and
    what a click does. The gesture's states are the shared `toad.pointer_gesture` ones."""

    # Screen selection starts before MouseDown reaches the control.
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        self._gesture: Gesture = NO_GESTURE
        super().__init__(*args, **kwargs)

    @abstractmethod
    def drag_start(self, event: events.MouseDown) -> None:
        ...

    @on(events.MouseDown)
    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            event.stop()
            self._gesture = PressedGesture(event.screen_offset)
            self.capture_mouse()
            self.drag_start(event)

    @on(events.MouseMove)
    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._gesture.holds_pointer:
            event.stop()
            self._gesture = self._gesture.moved(self, event.screen_offset)

    def can_replace_mouse_move(
        self, event: events.MouseMove, pending: events.MouseMove
    ) -> bool:
        # Both controls map the latest absolute position, not motion deltas.
        return self._gesture.holds_pointer and event.button == pending.button == 1

    @on(events.MouseUp)
    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == 1 and self._gesture.holds_pointer:
            event.stop()
            self._gesture = self._gesture.released(self, event.screen_offset)
            self.release_mouse()

    @on(events.MouseRelease)
    def on_mouse_release(self) -> None:
        self._gesture = NO_GESTURE

    @on(Click)
    def on_captured_click(self, event: Click) -> None:
        """The captured gesture already answered this press (``clicked`` or a drag); the click
        Textual sends after it must not reach a parent, such as a folded bar that opens on click."""
        if event.button == 1:
            event.stop()


class SidebarEdgeGrip(SidebarResizeGrip, CapturedDrag):
    """A Textual edge grip on `SideBar`: drags the bar's extent against its host."""

    @property
    def grip_surface(self) -> SideBar:
        return self.query_ancestor(SideBar)

    def grip_viewport_extent(self) -> int:
        bar = self.grip_surface
        return bar.placement.side.extent(bar.query_ancestor(Widget).content_size)

    def drag_start(self, event: events.MouseDown) -> None:
        self.begin_grip(event.screen_offset)


class SideBarToggle(
    SidebarToggleFace,
    SidebarFoldGrip,
    SidebarEdgeGrip,
    MutedText,
    CenteredContent,
    HoverSelection,
    DeclaredWidgetActions,
    PrimaryActivation,
    widgets.Static,
    actions=(ToggleSidebarAction,),
):
    """Collapse target spanning the conversation-facing resize edge."""

    native_theme = (
        NativeDeclaration.of(Styles.background, Variable(PrimaryColour.name), Percent(8)),
    )

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layer = "sidebar-toggle"

    @property
    def paint_highlighted(self):
        bar = self.query_ancestor(SideBar)
        return super().paint_highlighted or (bar.collapsed and bar.mouse_hover)

    can_focus = True

    class Pressed(Message):
        def __init__(self, *, focus: bool = True) -> None:
            super().__init__()
            self.focus = focus

    def __init__(self, collapsed: bool, *, edge: type[SidebarEdge], heading: str) -> None:
        super().__init__()
        self.heading = heading
        self.set_collapsed(collapsed, edge)

    def show_heading(self, heading: str, collapsed: bool, edge: type[SidebarEdge]) -> None:
        """The bar names what it shows now; only a changed name redraws."""
        if heading != self.heading:
            self.heading = heading
            self.set_collapsed(collapsed, edge)

    def set_collapsed(self, collapsed: bool, edge: type[SidebarEdge]) -> None:
        edge.size_toggle(self)
        self.styles.dock = edge.opposite().dock
        self.offset = edge.control_offset(0 if collapsed else 1)
        self.present_toggle(collapsed, edge, self.heading)

    def show_toggle(self, text: str, tooltip: str) -> None:
        if self.content != text:
            self.update(text, layout=False)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @property
    def primary_activation(self):
        return self.pointer_toggle

    def pointer_toggle(self) -> None:
        self.query_ancestor(SideBar).toggle(focus=False)

    def focus_on_click(self) -> bool:
        # Pointer activation is a visibility change. Focusing this handle first
        # rebuilds bindings, only to move focus again when the sidebar toggles.
        # It remains keyboard-focusable through normal Tab navigation.
        return False


class SidebarSlider(
    SidebarExtentTrack,
    MutedText,
    OneRow,
    FillWidth,
    PointerCursor,
    VisibleActions,
    StepsHorizontalCursor,
    CapturedDrag,
    ColourSelection,
    widgets.Static,
    can_focus=True,
):
    """A bottom-row pointer/keyboard slider; no polling or source snapshots."""

    highlight_foreground = AccentColour


    @dataclass
    class Changed(Message):
        slider: SidebarSlider
        value: int

    def __init__(self, minimum: int, maximum: int, value: int) -> None:
        super().__init__()
        self.start_track(minimum, maximum, value)
        self.tooltip = self.track_tooltip

    def set_range(self, minimum: int, maximum: int, value: int) -> None:
        super().set_range(minimum, maximum, value)
        self.refresh()

    def render(self) -> str:
        return self.track_text(self.size.width)

    def drag_to(self, position: Offset) -> None:
        value = self.value_at(position.x - self._drag_origin_x, self._drag_width, self._drag_reversed)
        if value != self.value:
            self.track_moved(self.query_ancestor(SideBar), value)
            self.refresh()

    def dragged(self) -> None:
        self.track_released(self.query_ancestor(SideBar))

    def clicked(self) -> None:
        """A press picks its value; letting go there ends the hold as a drag's release does."""
        self.track_released(self.query_ancestor(SideBar))

    def step_horizontal(self, direction: int) -> None:
        value = self.stepped(direction)
        if value != self.value:
            self.value = value
            self.refresh()
            self.post_message(self.Changed(self, value))

    def drag_start(self, event: events.MouseDown) -> None:
        # Keep the pressed track's mapping while its width/origin changes.
        self._drag_origin_x = self.region.x
        self._drag_width = self.size.width
        self._drag_reversed = self.reversed
        self.begin_track(self.query_ancestor(SideBar))
        self.drag_to(event.screen_offset)


class SidebarAction(
    MutedText,
    OneRow,
    AutoWidth,
    SidePadding,
    PointerCursor,
    MroProjection[None],
    Activates,
    HoverSelection,
    PlacementControl,
    widgets.Static,
    can_focus=True,
):
    """One spatial arrow or float/push action; the action's kind owns its cell. It is the
    Textual PlacementControl the SidebarPlacementAction family presents."""

    @dataclass
    class Pressed(Message):
        action: SidebarPlacementAction

    def __init__(self, action: SidebarPlacementAction) -> None:
        super().__init__(action.label, id=f"sidebar-{action.name}")
        self.action = action

    def set_shown(self, shown: bool) -> None:
        self.display = shown

    def set_label(self, label: str) -> None:
        self.update(label, layout=False)

    def set_tooltip(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.project_value(self.action)

    @handles(SidebarPlacementAction)
    def compact_cell(self, action: SidebarPlacementAction) -> None:
        """A plain action keeps its compact cell."""

    @handles(DirectionalSidebarPlacementAction)
    def direction_cell(self, action: DirectionalSidebarPlacementAction) -> None:
        self.styles.width = "1fr"
        self.styles.content_align = ("center", "middle")
        self.styles.text_style = "bold"

    @handles(FloatSidebarPlacementAction)
    def float_cell(self, action: FloatSidebarPlacementAction) -> None:
        self.styles.column_span = 2
        self.styles.width = "1fr"

    def activate(self) -> None:
        self.post_message(self.Pressed(self.action))

class SidebarResizeHandle(
    SidebarEdgeGrip,
    NoPadding,
    VisibleActions,
    StepsHorizontalCursor,
    StepsVerticalCursor,
    ColourSelection,
    widgets.Static,
    ToadNode,
    can_focus=True,
):
    """Drag the conversation-facing edge; the placement model owns the extent."""

    highlight_foreground = ForegroundColour

    theme_ink = NativeDeclaration.of(Styles.color, Variable(SuccessColour.name))
    ansi_ink = NativeDeclaration.of(Styles.color, Keyword("ansi_green"))

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        ink = self.app.colours.ink.choose(true_colour=self.theme_ink, ansi=self.ansi_ink)
        return (*super().native_declarations(), ink)


    def __init__(self, edge: type[SidebarEdge]) -> None:
        super().__init__()
        edge.size_handle(self)
        self.styles.dock = edge.opposite().dock
        self.tooltip = self.grip_tooltip

    def render(self) -> str:
        return self.query_ancestor(SideBar).placement.side.handle_text(self.size)

    def resize_by(self, direction: Offset) -> None:
        bar = self.query_ancestor(SideBar)
        placement = bar.placement
        bar.resize_to(placement.extent_percent + placement.side.sign * placement.side.coordinate(direction))

    def step_horizontal(self, direction: int) -> None:
        self.resize_by(Offset(direction, 0))

    def step_vertical(self, direction: int) -> None:
        self.resize_by(Offset(0, direction))


class BandSplitHandle(
    NoPadding,
    VisibleActions,
    StepsHorizontalCursor,
    CapturedDrag,
    ColourSelection,
    widgets.Static,
    ToadNode,
    can_focus=True,
):
    """Drag the line between two bars sharing a top or bottom band; the layout owns the split."""

    highlight_foreground = ForegroundColour

    def __init__(self) -> None:
        super().__init__()
        self.styles.width, self.styles.height = HeightSidebarEdge.splitter, "1fr"
        self.styles.dock = "right"
        self.styles.pointer = "ew-resize"
        self.tooltip = "Drag to share the band between the two sidebars"
        self.display = False

    def render(self) -> str:
        return "\n".join("│" for _ in range(self.size.height))

    @property
    def drawn_percent(self) -> int:
        """The split as the band draws it: the stored split may ask for less than a bar's
        minimum width, and a move starts from what the user sees."""
        bar = self.query_ancestor(SideBar)
        return round(100 * bar.region.width / max(1, self.band_width))

    @property
    def band_width(self) -> int:
        return self.query_ancestor(SideBar).query_ancestor(Widget).content_size.width

    def split_to(self, percent: int) -> None:
        bar = self.query_ancestor(SideBar)
        if self.app.sidebar_layout.set_split(bar.placement.side, percent):
            bar.arranged()

    def drag_start(self, event: events.MouseDown) -> None:
        self._start_point = event.screen_offset
        self._start_percent = self.drawn_percent
        self._drag_width = self.band_width

    def drag_to(self, position: Offset) -> None:
        delta = position.x - self._start_point.x
        self.split_to(self._start_percent + round(100 * delta / max(1, self._drag_width)))

    def step_horizontal(self, direction: int) -> None:
        self.split_to(self.drawn_percent + direction)


class ClearSidebarSearchAction(WidgetAction):
    """Clear the sidebar search text."""
    keys = {TextEntryMode: ("escape",)}

    def apply(self, context: SidebarSearch) -> None:
        context.clear_search()


class SidebarSearch(SidebarSearchField, DeclaredWidgetActions, widgets.Input, actions=(ClearSidebarSearchAction,)):
    """Sidebar text filter with a declared clear action."""

    def show_search(self, text: str) -> None:
        self.value = text


class SearchSidebarAction(WidgetAction):
    """Focus search in the sidebar containing the current selection."""

    keys = {TextEntryMode: ("slash",)}

    def available(self, sidebar: SideBar) -> bool:
        return sidebar.app.focused is not sidebar.search_input

    async def apply(self, sidebar: SideBar) -> None:
        sidebar.search_input.focus()


class SidebarContentStack(containers.Vertical):
    """One padded flow for content; padding never intercepts the outer handles."""

    hit_test_transparent = True

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layer = "sidebar-content"


class SidebarControls(AutoHeight, containers.Vertical):
    """The extent slider and placement actions under the panels."""



class SidebarLayoutActions(AutoHeight, FillWidth, HiddenOverflow, containers.Grid):
    """Placement actions, two to a row."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_size_columns = 2
        self.styles.grid_columns = "1fr 1fr"
        self.styles.grid_rows = "1"


class SideBar(
    SidebarSurface,
    HiddenOverflow,
    FillHeight,
    AutoWidth,
    DismissibleControl,
    WorkspaceHosted,
    TonePaint,
    CoreEventReceiver,
    containers.Vertical,
    ToadNode,
    actions=(SearchSidebarAction,),
):
    tone = SidebarToneColour
    BINDING_GROUP_TITLE = "Sidebar"

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.layers = ("sidebar-content", "sidebar-toggle")
        self.styles.dock = "none"
        self.styles.layer = "comms-sidebar"
        self.styles.scrollbar_size_horizontal = self.styles.scrollbar_size_vertical = 0

    collapsed = reactive(False)
    search = reactive("")

    class Dismiss(Message):
        pass

    @dataclass(frozen=True)
    class Panel(PanelSpec):
        """Textual's panel: the toolkit-neutral `PanelSpec` fields plus the
        Textual-widget references each panel composes. The spec fields
        (`title`, `flex`, `collapsed`, `id`) come from the shared base so
        Qt's panel spec addresses the same panel by the same key when both
        read/write the one `SidebarState.panels_collapsed` owner."""

        widget: SidebarPanelWidget = None  # type: ignore[assignment]
        header_control: Widget | None = None

    @property
    def placement_identity(self) -> type[SidebarPlacement]:
        return self._placement_identity

    def __init__(
        self,
        *panels: Panel,
        placement_identity: type[SidebarPlacement],
        name: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        hide: bool = False,
        defer_mount: bool = False,
    ) -> None:
        self._placement_identity = placement_identity
        super().__init__(name=name, classes=classes, disabled=disabled)
        self.panels: list[SideBar.Panel] = [*panels]
        # The shared owner of the sidebar search text and row-match decision. Qt's
        # sidebar holds its own `SidebarFilter` and asks the same `matches(name)`
        # question when drawing rows — the `watch_search` push below keeps this
        # the single source of truth even though Textual's reactive remains the
        # input-change mechanism inside Textual itself.
        self.filter = SidebarFilter()
        self.content_stack = SidebarContentStack()
        self.new_shell()
        self.hide = hide
        self.extent_slider = SidebarSlider(
            SidebarSlider.floor, SidebarLayout.maximum_percent,
            SidebarLayout.minimum_percent,
        )
        self.panel_state: SidebarPanels = AbsentPanels() if defer_mount else LoadedPanels()
        self._presented_collapsed: bool | None = None
        self._pressed_folded = False
        self._presented_layout: BarDisplay = BarDisplay()

    def invalidate_controls(self) -> None:
        self._presented_layout = BarDisplay()

    def new_shell(self) -> None:
        """The search box, panel viewport and controls a loaded sidebar shows. A sidebar whose
        panels are absent mounts none of them (each tab's collapsed sidebar built and styled
        them for nothing), and a removed widget is never mounted again, so every load gets
        its own."""
        self.search_input = SidebarSearch(value=self.search, placeholder=SidebarSearch.search_placeholder,
                                          compact=True)
        self.panels_viewport: SidebarViewport = SidebarViewport()
        self.layout_controls = SidebarControls()
        self.shell_lead, self.shell_tail = self.lead_parts(), self.tail_parts()

    def lead_parts(self) -> tuple[Widget, ...]:
        """Widgets above the search box: none, unless a sidebar shows more while it holds the
        window alone (`ChannelsSidebar`)."""
        return ()

    def tail_parts(self) -> tuple[Widget, ...]:
        """Widgets below the panels and controls, as `lead_parts`."""
        return ()

    def _compose_shell(self) -> ComposeResult:
        yield from self.shell_lead
        yield self.search_input
        with self.panels_viewport:
            yield from self._compose_panels()
        with self.layout_controls:
            yield from self._compose_controls()
        yield from self.shell_tail

    @cached_property
    def toggle_control(self) -> SideBarToggle:
        return SideBarToggle(self.collapsed, edge=self.placement.side, heading=self.heading)

    @property
    def heading(self) -> str:
        """The placement names what this bar shows, from the titles of the tabs being viewed."""
        app = self.app
        return self.placement_identity.heading(
            tab.title for tab in app.open_tabs if tab.mode_name == app.selected_mode)

    @handles(core_events.SessionSelected, core_events.OpenTabsChanged)
    async def viewed_changed(self, event: core_events.SessionSelected | core_events.OpenTabsChanged) -> None:
        self.present_alone()
        self.toggle_control.show_heading(self.heading, self.collapsed, self.placement.side)

    def validate_collapsed(self, collapsed: bool) -> bool:
        """A bar holding the window alone is open whatever its kept fold
        (`SidebarLayout.is_collapsed` says the same for Qt's bars)."""
        return collapsed and not self.holds_alone

    def present_alone(self) -> None:
        """The selected view changed: a bar that holds the window now opens, and one that no
        longer does takes its kept fold again (the sole role's fold is the saved
        `sidebar.hide`; a bar that never holds the window keeps its own)."""
        if self.placement_identity is not self.sidebar_layout.sole_role:
            return
        self.collapsed = SETTINGS.sidebar.hide.bind(self.app.saved_settings.state).value
        self.invalidate_controls()
        self.app.workspace_chrome.refresh_layout()

    @cached_property
    def resize_handle(self) -> SidebarResizeHandle:
        return SidebarResizeHandle(self.placement.side)

    @cached_property
    def split_handle(self) -> BandSplitHandle:
        return BandSplitHandle()

    @property
    def panels_loaded(self) -> bool:
        return self.panel_state.loaded

    @property
    def navigation(self) -> SidebarState:
        return self.app.sidebar_state

    def mount_collapse(self) -> None:
        app = self.app
        self.observe_core(app.saved_settings.events)
        self.collapsed = SETTINGS.sidebar.hide.bind(app.saved_settings.state).value

    def store_collapsed(self, value: bool) -> None:
        app = self.app
        app.saved_settings.set(SETTINGS.sidebar.hide, value)
        self.collapsed = SETTINGS.sidebar.hide.bind(app.saved_settings.state).value

    @on(events.Mount)
    def on_mount(self) -> None:
        self.trap_focus()
        self.observe_core(self.app.events)
        self.mount_collapse()
        self.watch_collapsed(self.collapsed)
        self.schedule_hydration()

    def schedule_hydration(self) -> None:
        if self.wants_panels:
            self.panel_state.schedule(self)

    @property
    def wants_panels(self) -> bool:
        """A shown sidebar loads its panels."""
        return self.presentation_visible

    @property
    def presentation_visible(self) -> bool:
        """Native attachment owns whether this retained resource may present."""
        return (
            self.is_attached
            and not self.is_leaving
            and self.screen.is_current
            and self.display
            and all(
                ancestor.display
                for ancestor in self.ancestors
                if isinstance(ancestor, Widget)
            )
        )

    def _start_hydration(self) -> None:
        self.panel_state.start(self)

    async def _hydrate_panels(self) -> None:
        # A screen covering the workspace, or a hidden ancestor, does not stop a load
        # it finds midway: stopping left panels mounted without their controls and no
        # state that would ever finish them. Leaving the view cancels this worker.
        await self.content_stack.mount_all(
            (*self.shell_lead, self.search_input, self.panels_viewport, self.layout_controls,
             *self.shell_tail))
        await self.panels_viewport.mount_all(self._compose_panels())
        await self.layout_controls.mount_all(self._compose_controls())
        self.panel_state = LoadedPanels()
        self.invalidate_controls()
        await self.panels_hydrated()
        self.restore_navigation()

    async def panels_hydrated(self) -> None:
        """The sidebar declaration completes its panel preparation."""

    def compose(self) -> ComposeResult:
        yield self.toggle_control
        yield self.resize_handle
        yield self.split_handle
        with self.content_stack:
            if self.panels_loaded:
                yield from self._compose_shell()

    @on(widgets.Input.Changed)
    def search_changed(self, event: widgets.Input.Changed) -> None:
        if event.input is self.search_input:
            event.stop()
            self.search = event.value

    def watch_search(self, value: str) -> None:
        """Push the reactive's new text into the shared owner so both frontends read
        the same match decision. The reactive stays the hook Textual's
        `SearchFollower` already watches; the owner is what Qt's sidebar reads."""
        self.filter.text = value

    def panel_entries(self):
        return iter(self.panels)

    def _compose_panels(self) -> ComposeResult:
        yield from self.panels_viewport.panel_frames(self.panel_entries(), self.navigation)

    def _compose_controls(self) -> ComposeResult:
        yield self.extent_slider
        yield SidebarLayoutActions(*(SidebarAction(action) for action in self.placement_actions()))

    @on(events.Show)
    def on_show(self) -> None:
        self.restore_navigation()

    def present_controls(self) -> bool:
        if not self.presentation_visible:
            self.invalidate_controls()
            return False
        placement = self.placement
        directions = self.app.sidebar_layout.directions(self.placement_identity)
        current = PresentedBar(
            presentation=BarPresentation.from_placement(
                placement, collapsed=self.collapsed, directions=directions,
                leads_band=self.app.sidebar_layout.splits_after(self.placement_identity, {
                    bar.placement_identity: bar.collapsed
                    for bar in self.app.workspace_chrome.presented_sidebars()}),
            ),
            extent_percent=placement.extent_percent,
        )
        previous = self._presented_layout
        if previous.matches(current):
            return False
        self._presented_layout = current
        slider = self.extent_slider
        if previous.controls_changed(current):
            edge = placement.side
            self.content_stack.styles.padding = self.content_padding()
            self.toggle_control.set_collapsed(self.collapsed, edge)
            # Holding the window alone there is nothing beside the bar to fold it for or to
            # grip: only its content shows.
            alone = self.holds_alone
            self.toggle_control.display = not alone
            self.layout_controls.display = self.controls_wanted and not alone
            handle = self.resize_handle
            edge.size_handle(handle)
            handle.styles.dock = edge.opposite().dock
            handle.display = not self.collapsed and not alone
            self.split_handle.display = current.presentation.leads_band
            if self.panels_loaded:
                self.present_extent_track(slider)
                self.present_placement_controls(self.layout_controls.query(SidebarAction),
                                                self.app.sidebar_layout, self.placement_identity)
        if slider.value != placement.extent_percent:
            slider.value = placement.extent_percent
            slider.refresh()
        return True

    @property
    def sidebar_layout(self) -> SidebarLayout:
        return self.app.sidebar_layout

    def toggle_controls(self) -> None:
        self.controls_wanted = not self.controls_wanted
        self.layout_controls.display = self.controls_wanted and not self.holds_alone

    @property
    def client(self) -> ToadApp:
        return self.app

    def lay_out(self) -> None:
        self.app.workspace_chrome.refresh_layout()

    @on(SidebarSlider.Changed)
    def on_sidebar_slider(self, event: SidebarSlider.Changed) -> None:
        """A keyboard step is a whole hold: stepping to 0 folds, keeping the extent it had."""
        event.stop()
        restore = self.placement.extent_percent
        self.extent_dragged(event.value)
        self.extent_released(event.value, restore)

    def fold(self, collapsed: bool) -> None:
        if collapsed != self.collapsed:
            self.toggle(focus=False)

    @on(SidebarAction.Pressed)
    def on_sidebar_action(self, event: SidebarAction.Pressed) -> None:
        event.stop()
        self.apply_placement_action(event.action)

    def restore_navigation(self) -> bool:
        changed = self._presented_collapsed != self.collapsed
        if changed:
            self.watch_collapsed(self.collapsed)
        else:
            self.app.workspace_chrome.refresh_layout()
        navigation = self.navigation
        for panel in self.query(SideBarCollapsible):
            title = str(panel.title)
            if title in navigation.panels_collapsed:
                panel.collapsed = navigation.is_panel_collapsed(title)
        return changed

    def watch_collapsed(self, collapsed: bool) -> None:
        if not self.presentation_visible:
            # Keep shared intent current without native work before attachment,
            # while hidden or during retirement. Activation applies the latest
            # value inside its render transaction.
            return
        if not collapsed:
            self.schedule_hydration()
        self._presented_collapsed = collapsed
        # One content flow hides without retiring its retained children.
        self.content_stack.display = not collapsed
        self.tooltip = "Expand sidebar" if collapsed else None
        self.toggle_control.set_collapsed(collapsed, self.placement.side)
        self.toggle_control.refresh_paint()
        for panel in self.panels:
            panel.widget.sidebar_visibility_changed()
        self.invalidate_controls()
        self.app.workspace_chrome.refresh_layout()

    def render(self) -> str:
        return self.placement.side.toggle_symbol(self.collapsed) if self.collapsed else ""

    @handles(PreferenceChanged)
    async def _settings_changed(self, event: PreferenceChanged) -> None:
        if SETTINGS.sidebar.hide.matches(event.field):
            self.collapsed = event.field.value

    @on(SideBarToggle.Pressed)
    def on_toggle_pressed(self, event: SideBarToggle.Pressed) -> None:
        event.stop()
        self.toggle(focus=event.focus)

    @on(events.MouseDown)
    def on_strip_press(self, event: events.MouseDown) -> None:
        """A press that reaches the bar itself: no captured control (slider, handle, strip)
        owned it. Only such a press, on a folded bar, opens it when it clicks."""
        self._pressed_folded = self.collapsed and event.button == 1

    @on(Click)
    def on_click(self, event: Click) -> None:
        pressed_folded, self._pressed_folded = self._pressed_folded, False
        if self.collapsed and event.button == 1 and pressed_folded:
            event.stop()
            self.toggle(focus=False)

    @on(events.Enter)
    @on(events.Leave)
    def gutter_hover_changed(self) -> None:
        if self.presentation_visible:
            self.toggle_control.refresh_paint()

    def focus_contents(self):
        self.panels_viewport.focus()

    def toggle(self, *, focus: bool = True) -> None:
        collapsed = not self.collapsed
        return_focus = collapsed and (focus or self.has_focus_within)
        if return_focus and self.presentation_visible:
            # Return input focus before native Hide reconstructs its focus chain.
            self.screen.focus_sidebar_return()
        self.store_collapsed(collapsed)
        if collapsed:
            if return_focus:
                self.post_message(self.Dismiss())
        elif focus:
            # Panels are already displayed by the synchronous watcher. Queue
            # native focus now so its highlight can share the opening frame,
            # rather than waiting for a painted frame to request another one.
            if self.panels_loaded:
                self.focus_contents()
            else:
                self.schedule_hydration()

    def reveal(self) -> None:
        self.store_collapsed(False)

    def dismiss_control(self) -> None:
        if SETTINGS.sidebar.hide.bind(self.app.saved_settings.state).value:
            self.collapsed = True
        self.post_message(self.Dismiss())


class PanelBody(FillHeight, containers.Vertical):
    """The space left below the selected-view menu."""


class PanelPage(SidebarPanelHost, PanelBody):
    """The original panel and its controls, retained while another entry is selected."""

    def reveal(self):
        menu = self.query_ancestor(PanelMenu)
        menu.picker.value = next(entry for entry, page in menu.pages.items() if page is self)


class PanelPicker(OneRow, FillWidth, widgets.Select):
    """One compact selector over the entries supplied by the viewed object."""


class PanelMenu(PanelMenuModel[SideBar.Panel], FillHeight, containers.Vertical):
    """Discover once from the owner; mount each original panel only when selected."""

    def __init__(self, entries, navigation: SidebarState, scope: ViewSettingsScope):
        super().__init__()
        self.entries = tuple(entries)
        self.navigation = navigation
        self.scope = scope
        selected = self.initial_entry()
        self.picker = PanelPicker(((entry.title, entry) for entry in self.entries),
                                 value=selected, allow_blank=False, compact=True)
        self.body = PanelBody()
        self.pages: dict[SideBar.Panel, PanelPage] = {}

    def compose(self):
        yield self.picker
        yield self.body

    @on(events.Mount)
    async def open_selection(self):
        await self.show_panel(self.picker.value)
        self.run_worker(self.load_configuration(), group="configuration-panels", exclusive=True)

    async def load_configuration(self):
        try:
            entries = await self.scope.configuration_action_panels()
        except CLI_FAILURES as error:
            self.app.show_error(error, "Object settings")
            return
        if not self.is_attached:
            return
        selected = self.picker.value
        self.entries += tuple(entries)
        with self.prevent(widgets.Select.Changed):
            self.picker.set_options((entry.title, entry) for entry in self.entries)
            self.picker.value = selected

    @on(widgets.Select.Changed)
    async def selection_changed(self, event):
        if event.select is self.picker and event.value is not widgets.Select.NULL:
            event.stop()
            await self.show_panel(event.value)

    async def show_panel(self, entry):
        for panel, page in self.pages.items():
            if page.display and panel is not entry:
                panel.widget.finish()
            page.display = panel is entry
            panel.widget.sidebar_visibility_changed()
        if entry not in self.pages:
            await self.body.mount(self.page(entry))
        self.remember_entry(entry)
        entry.widget.sidebar_visibility_changed()

    def entry_identity(self, entry) -> object:
        return entry.widget.panel_identity

    def realize_page(self, entry):
        children = (() if entry.header_control is None else (entry.header_control,))
        return PanelPage(*children, entry.widget, id=entry.id)

    def activate(self, widget):
        self.picker.value = next(entry for entry in self.entries if entry.widget is widget)

    def finish(self):
        for entry in self.pages:
            entry.widget.finish()


class ThreadSidebar(ThreadSidebarContents[SideBar.Panel], SideBar):
    placement_type = ThreadSidebarPlacement

    def panel_entries(self):
        return iter(self.thread_entries(self.query_ancestor(ViewSettingsScope)))

    def roster_entries(self):
        return SideBar.panel_entries(self)

    def action_entries(self, view):
        return view.action_panels

    def setting_entries(self, view):
        return view.configuration_panels

    def _compose_panels(self):
        yield PanelMenu(self.panel_entries(), self.navigation, self.query_ancestor(ViewSettingsScope))

    def focus_contents(self):
        self.query_one(PanelPicker).focus()

    def reveal_panel(self, widget):
        self.query_one(PanelMenu).activate(widget)

    def __init__(self, *panels, state: SidebarState, **kwargs):
        self.state = state
        super().__init__(*panels, placement_identity=self.placement_type, hide=True, **kwargs)
        self.collapsed = self.hide

    @property
    def navigation(self) -> SidebarState:
        return self.state

    def mount_collapse(self) -> None:
        self.collapsed = self.hide

    def store_collapsed(self, value: bool) -> None:
        self.collapsed = value


class LazyThreadSidebar(ThreadSidebar):
    """Create panel widgets only when this view's sidebar opens."""

    def __init__(self, *panels, **kwargs):
        super().__init__(*panels, defer_mount=True, **kwargs)

    @property
    def wants_panels(self) -> bool:
        return super().wants_panels and not self.collapsed

    @abstractmethod
    def make_panels(self): ...

    def _compose_panels(self):
        if not self.panels:
            self.panels.extend(self.make_panels())
        yield from super()._compose_panels()
