from __future__ import annotations

from textual._callback import invoke

from metaclass_registry.mro_dispatch import handles
from toad.core_event_carrier import CoreEventReceiver
from toad.core import events as core_events
from textual.content import Content
from toad.widget_actions import ApplicationAction, ActivationKeys, Activates, DismissibleControl, WidgetAction, DeclaredWidgetActions, MovesHorizontalCursor
from textual.document._editing import EditingMode
from toad.widgets.comms_menu import ContextMenu
from toad.core.preference_events import PreferenceChanged
from toad.preferences import SETTINGS
from dataclasses import dataclass
import asyncio
from typing import TYPE_CHECKING, ClassVar

from textual import containers, events, on, widgets
from textual.app import ComposeResult
from textual.events import Click
from textual.geometry import Offset
from textual.message import Message
from textual.reactive import reactive
from textual._activation import PrimaryActivation
from textual.widget import Widget

from ui_theme.scheme import SidebarToneColour, AccentColour, ForegroundColour

from toad.widget_view import WorkspaceHosted
from toad.tone_paint import TonePaint
from toad.widgets.selection import HoverSelection, ColourSelection
from toad.session_tracker import SidebarState
from toad.sidebar_layout import (
    Side,
    SidebarGeometry,
    SidebarPlacement,
    SidebarPlacementAction,
    SidebarShift,
)
from toad.widgets.sidebar_viewport import SidebarHeader, SidebarViewport
from toad.app_node import ToadNode

if TYPE_CHECKING:
    from toad.tab_order import TabOrder


@dataclass(frozen=True)
class BarPresentation:
    side: Side
    order: int
    floating: bool
    collapsed: bool
    directions: tuple[type[SidebarShift], ...]
    compact: bool

    @classmethod
    def from_placement(
        cls,
        placement: SidebarPlacement,
        *,
        collapsed: bool,
        directions: dict[Side, SidebarShift],
        width: int,
    ) -> BarPresentation:
        return cls(
            placement.side,
            placement.order,
            placement.floating,
            collapsed,
            tuple(type(action) for action in directions.values()),
            all(action.available for action in directions.values()) and width - 4 < 21,
        )


@dataclass(frozen=True)
class PresentedBar:
    presentation: BarPresentation
    geometry: SidebarGeometry
    width_percent: int


class SidebarPanelWidget(Widget):
    """Every sidebar panel accepts visibility changes; passive panels do nothing."""

    def sidebar_visibility_changed(self) -> None:
        pass


class SidebarVisibilityObserver(SidebarPanelWidget):
    """A panel whose viewport and active presentation belong to its enclosing sidebar."""

    @property
    def scroll_container(self) -> SidebarViewport:
        return self.query_ancestor(SideBar).panels_viewport

    def preserve_reader(self, placements) -> None:
        self.scroll_container.preserve_reader(placements)


class SideBarCollapsible(widgets.Collapsible, inherit_css=False):
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

    DEFAULT_CSS = """
    SideBarCollapsible, SideBarCollapsible:ansi {
        width: 1fr;
        height: auto;
        min-height: 1;
        padding: 0;
        margin: 0;
        border-top: none;
        background: transparent;
    }
    SideBarCollapsible > CollapsibleTitle {
        width: 1fr;
        padding: 0;
    }
    SideBarCollapsible > .sidebar-header {
        height: 1;
    }
    SideBarCollapsible > .sidebar-header > CollapsibleTitle {
        width: 1fr;
        height: 1;
        padding: 0;
    }
    SideBarCollapsible > Contents {
        height: auto;
        padding: 0;
    }
    SideBarCollapsible.-flex {
        height: auto;
        min-height: 12;
    }
    SideBarCollapsible.-flex > Contents {
        height: auto;
        overflow: hidden hidden;
    }
    SideBarCollapsible.-collapsed {
        height: auto;
        min-height: 1;
    }
    SideBarCollapsible.-collapsed > Contents { display: none; }
    """

    def __init__(
        self, *children: Widget, header_control: Widget | None = None, **kwargs
    ):
        super().__init__(*children, **kwargs)
        self.header_control = header_control

    def watch_collapsed(self, collapsed: bool) -> None:
        if self.is_attached:
            self.query_ancestor(SideBar).navigation.panels_collapsed[
                str(self.title)
            ] = collapsed

    def compose(self) -> ComposeResult:
        if self.header_control is None:
            yield from super().compose()
        else:
            with SidebarHeader(classes="sidebar-header"):
                yield self._title
                yield self.header_control
            with self.Contents():
                yield from self._contents_list


class ToggleSidebarAction(WidgetAction):
    """Toggle the sidebar and focus its contents."""
    keys = {EditingMode: ("enter", "space")}

    def apply(self, context: SideBarToggle) -> None:
        context.post_message(context.Pressed())


class SideBarToggle(HoverSelection, DeclaredWidgetActions, PrimaryActivation, widgets.Static,
                    actions=(ToggleSidebarAction,)):
    """Full-height collapse target beside the conversation-facing resize edge."""

    @property
    def paint_highlighted(self):
        bar = self.query_ancestor(SideBar)
        return super().paint_highlighted or (bar.collapsed and bar.mouse_hover)

    ALLOW_SELECT = False

    DEFAULT_CSS = """
    SideBarToggle {
        dock: right;
        width: 3;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        background: $primary 8%;
        layer: sidebar-toggle;
    }
    """

    can_focus = True

    class Pressed(Message):
        def __init__(self, *, focus: bool = True) -> None:
            super().__init__()
            self.focus = focus

    def __init__(self, collapsed: bool = False, *, right: bool = False) -> None:
        super().__init__()
        self.right = right
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self.styles.dock = "left" if self.right else "right"
        self.offset = (0 if collapsed else 1 if self.right else -1, 0)
        text = (
            ("<" if collapsed else ">") if self.right else (">" if collapsed else "<")
        )
        if self.content != text:
            self.update(text, layout=False)
        tooltip = "Expand sidebar" if collapsed else "Collapse sidebar"
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

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.pointer_toggle()


class HeaderButton(ActivationKeys, HoverSelection, widgets.Static, can_focus=True):
    """One compact, keyboard-accessible control in the top bar, on the bar's own tone."""

    DEFAULT_CSS = """
    HeaderButton {
        width: 7;
        height: 3;
        content-align: center middle;
        color: $text;
        text-style: bold;
        pointer: pointer;
    }
    HeaderButton:disabled {
        color: $text-disabled;
        pointer: default;
    }
    """

class TabHistoryButton(HeaderButton, ToadNode):
    """Back or forward through visited tabs."""

    direction: ClassVar[int]
    label: ClassVar[str]
    button_id: ClassVar[str]
    available_tooltip: ClassVar[str]
    unavailable_tooltip: ClassVar[str]

    def __init__(self) -> None:
        super().__init__(self.label, id=self.button_id)
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
    button_id = "tab-back"
    available_tooltip = "Back through visited tabs"
    unavailable_tooltip = "No earlier visited tab"


class ForwardTabButton(TabHistoryButton):
    direction = +1
    label = "──>"
    button_id = "tab-forward"
    available_tooltip = "Forward through visited tabs"
    unavailable_tooltip = "No later visited tab"


class MainMenuButton(HeaderButton):
    """Own the declared application menu and its full-height hamburger."""

    def __init__(self) -> None:
        super().__init__(id="main-menu")
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
            Offset(self.region.x, self.region.bottom),
            "Toad",
            ApplicationAction.menu(self.app),
            callback=self.chosen,
        )

    async def chosen(self, action: ApplicationAction | None) -> None:
        if action is not None:
            await invoke(action.apply, self.app)


class TabHistoryControls(CoreEventReceiver, containers.HorizontalGroup, ToadNode):
    """Left-sidebar controls shared by native thread and channel screens."""

    DEFAULT_CSS = """
    TabHistoryControls {
        width: auto;
        height: 3;
        margin: 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield MainMenuButton()
        yield BackTabButton()
        yield ForwardTabButton()

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


class CapturedDrag:
    """One captured pointer gesture; controls own its coordinate mapping."""

    # Screen selection starts before MouseDown reaches the control.
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        self._dragging = False
        super().__init__(*args, **kwargs)

    def drag_start(self, event: events.MouseDown) -> None:
        raise NotImplementedError

    def drag_to(self, screen_x: int) -> None:
        raise NotImplementedError

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            event.stop()
            self._dragging = True
            self.capture_mouse()
            self.drag_start(event)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging:
            event.stop()
            self.drag_to(event.screen_x)

    def can_replace_mouse_move(
        self, event: events.MouseMove, pending: events.MouseMove
    ) -> bool:
        # Both controls map the latest absolute position, not motion deltas.
        return self._dragging and event.button == pending.button == 1

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == 1 and self._dragging:
            event.stop()
            self.drag_to(event.screen_x)
            self._dragging = False
            self.release_mouse()

    def on_mouse_release(self) -> None:
        self._dragging = False


class SidebarSlider(MovesHorizontalCursor, CapturedDrag, ColourSelection, widgets.Static, can_focus=True):
    """A bottom-row pointer/keyboard slider; no polling or source snapshots."""

    highlight_foreground = AccentColour

    DEFAULT_CSS = """
    SidebarSlider { height: 1; width: 1fr; color: $text-muted; pointer: pointer; }
    """

    @dataclass
    class Changed(Message):
        slider: SidebarSlider
        value: int

    def __init__(self, minimum: int, maximum: int, value: int) -> None:
        super().__init__()
        self.minimum = minimum
        self.maximum = maximum
        self.value = value
        self.reversed = False
        self.tooltip = "Drag or use ←/→ to resize (15–50% of screen)"

    def set_range(self, minimum: int, maximum: int, value: int) -> None:
        self.minimum, self.maximum = minimum, max(minimum, maximum)
        self.value = max(self.minimum, min(self.maximum, value))
        self.refresh()

    def render(self) -> str:
        label = f"{self.value:2d}%"
        track = max(1, self.size.width - len(label) - 1)
        ratio = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        if self.reversed:
            ratio = 1 - ratio
        thumb = round(ratio * (track - 1))
        line = "".join("●" if index == thumb else "─" for index in range(track))
        return f"{line} {label}" if self.reversed else f"{label} {line}"

    def drag_to(self, screen_x: int) -> None:
        x = screen_x - self._drag_origin_x
        width = self._drag_width
        reverse = self._drag_reversed
        label_width = 4
        track = max(1, width - label_width)
        if reverse:
            label_width = 0
        ratio = max(0.0, min(1.0, (x - label_width) / max(1, track - 1)))
        if reverse:
            ratio = 1 - ratio
        value = round(self.minimum + ratio * (self.maximum - self.minimum))
        if value != self.value:
            self.value = value
            self.refresh()
            self.post_message(self.Changed(self, value))

    def cursor_horizontal(self, direction: int) -> None:
        if self.reversed:
            direction = -direction
        value = max(self.minimum, min(self.maximum, self.value + direction))
        if value != self.value:
            self.value = value
            self.refresh()
            self.post_message(self.Changed(self, value))

    def drag_start(self, event: events.MouseDown) -> None:
        # Keep the pressed track's mapping while its width/origin changes.
        self._drag_origin_x = self.region.x
        self._drag_width = self.size.width
        self._drag_reversed = self.reversed
        self.drag_to(event.screen_x)


class SidebarAction(Activates, HoverSelection, widgets.Static, can_focus=True):
    """One spatial arrow or float/push action."""

    DEFAULT_CSS = """
    SidebarAction { height: 1; width: auto; padding: 0 1; color: $text-muted; pointer: pointer; }
    SidebarAction.-direction { width: 7; content-align: center middle; text-style: bold; }
    """

    @dataclass
    class Pressed(Message):
        action: SidebarPlacementAction

    def __init__(self, action: SidebarPlacementAction) -> None:
        super().__init__(action.label, id=f"sidebar-{action.declared_name}")
        self.action = action
        self.set_class(action.directional, "-direction")

    def activate(self) -> None:
        self.post_message(self.Pressed(self.action))

class SidebarResizeHandle(
    MovesHorizontalCursor, CapturedDrag, ColourSelection, widgets.Static, ToadNode, can_focus=True
):
    """Drag the conversation-facing edge; the placement model owns the width."""

    highlight_foreground = ForegroundColour

    DEFAULT_CSS = """
    SidebarResizeHandle {
        dock: right; width: 1; height: 1fr; padding: 0;
        color: $success; pointer: ew-resize;
    }
    SidebarResizeHandle:ansi { color: ansi_green; }
    """

    def __init__(self) -> None:
        super().__init__(id="sidebar-resize-handle")
        self.tooltip = "Drag toward the center to widen the sidebar"

    def render(self) -> str:
        return "\n".join("│" for _ in range(self.size.height))

    def drag_to(self, screen_x: int) -> None:
        bar = self.query_ancestor(SideBar)
        if bar.id is None or bar.parent is None:
            return
        app = self.app
        direction = -1 if app.sidebar_layout.get(bar.id).side == "right" else 1
        width = self._start_width + direction * (screen_x - self._start_x)
        percent = round(100 * width / max(1, bar.screen.size.width))
        if app.sidebar_layout.width(bar.id, percent):
            app.workspace_chrome.refresh_layout()

    def cursor_horizontal(self, direction: int) -> None:
        bar = self.query_ancestor(SideBar)
        bar.width_slider.cursor_horizontal(direction)

    def drag_start(self, event: events.MouseDown) -> None:
        self._start_x = event.screen_x
        self._start_width = self.query_ancestor(SideBar).size.width


class ClearSidebarSearchAction(WidgetAction):
    """Clear the sidebar search text."""
    keys = {EditingMode: ("escape",)}

    def apply(self, context: SidebarSearch) -> None:
        context.value = ""


class SidebarSearch(DeclaredWidgetActions, widgets.Input, actions=(ClearSidebarSearchAction,)):
    """Sidebar text filter with a declared clear action."""


class SearchSidebarAction(WidgetAction):
    """Focus search in the sidebar containing the current selection."""

    keys = {EditingMode: ("slash",)}

    def available(self, sidebar: SideBar) -> bool:
        return sidebar.app.focused is not sidebar.search_input

    async def apply(self, sidebar: SideBar) -> None:
        sidebar.search_input.focus()


class SideBar(DismissibleControl, WorkspaceHosted, TonePaint, CoreEventReceiver,
              containers.Vertical, ToadNode, actions=(SearchSidebarAction,)):
    tone = SidebarToneColour
    BINDING_GROUP_TITLE = "Sidebar"
    DEFAULT_CSS = """
    SideBar {
        layers: sidebar-content sidebar-toggle;
        dock: none;
        layer: comms-sidebar;
        overflow: hidden;
        scrollbar-size: 0 0;
        height: 1fr;
        width: auto;
        border: none;
    }
    SideBar > SidebarViewport {
        width: 1fr;
        height: 1fr;
        margin: 0 4 0 0;
        layer: sidebar-content;
        overflow: auto auto;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
    }
    SideBar > #sidebar-controls {
        width: 1fr;
        height: auto;
        margin: 0 4 0 0;
        layer: sidebar-content;
    }
    SideBar #sidebar-layout-actions { height: 1; width: 1fr; overflow: hidden hidden; grid-size: 3; grid-columns: 7 7 auto; }
    SideBar #sidebar-layout-actions.-compact {
        grid-size: 2; grid-columns: 1fr 1fr; height: 2;
    }
    SideBar #sidebar-layout-actions.-compact > #sidebar-float { column-span: 2; width: 1fr; }
    SideBar.-right {
        border-right: none;
        border-left: none;
    }
    SideBar.-right > SideBarToggle { dock: left; }
    SideBar.-right > SidebarResizeHandle { dock: left; }
    SideBar.-right > SidebarViewport, SideBar.-right > #sidebar-controls { margin: 0 0 0 4; }
    """

    collapsed = reactive(False)
    search = reactive("")
    PANEL_WORKER_GROUP = "panels"

    class Dismiss(Message):
        pass

    @dataclass(frozen=True)
    class Panel:
        title: str
        widget: SidebarPanelWidget
        flex: bool = False
        collapsed: bool = False
        id: str | None = None
        header_control: Widget | None = None

    def __init__(
        self,
        *panels: Panel,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        hide: bool = False,
        right: bool = False,
        defer_mount: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.panels: list[SideBar.Panel] = [*panels]
        self.search_input = SidebarSearch(placeholder="Search", compact=True)
        self.search_input.styles.layer = "sidebar-content"
        self.panels_viewport: SidebarViewport = SidebarViewport()
        self.hide = hide
        self.right = right
        self.width_slider = SidebarSlider(15, 50, 40 if not right else 34)
        self._panels_loaded = not defer_mount
        self._panels_loading = False
        self._panels_ready = asyncio.Event()
        self._presented_collapsed: bool | None = None
        self._presented_layout: PresentedBar | None = None
        self.set_class(right, "-right")

    @property
    def panels_loaded(self) -> bool:
        return self._panels_loaded

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

    def on_mount(self) -> None:
        self.trap_focus()
        self.mount_collapse()
        self.watch_collapsed(self.collapsed)
        if self._panels_loaded:
            self._panels_ready.set()
        else:
            self.schedule_hydration()

    def schedule_hydration(self) -> None:
        if not self._panels_loaded and not self._panels_loading:
            self.screen.frame_presentation.defer(self, self._start_hydration)

    @property
    def presentation_visible(self) -> bool:
        return (
            self.screen.is_current
            and self.display
            and all(
                ancestor.display
                for ancestor in self.ancestors
                if isinstance(ancestor, Widget)
            )
        )

    def _start_hydration(self) -> None:
        if (
            self._panels_loaded
            or self._panels_loading
            or not self.is_attached
            or not self.presentation_visible
            or self.is_leaving
        ):
            return
        self._panels_loading = True
        self.run_worker(self._hydrate_panels(), group=self.PANEL_WORKER_GROUP)

    async def _hydrate_panels(self) -> None:
        try:
            await self.panels_viewport.mount_all(self._compose_panels())
            if not self.is_attached or self.is_leaving or not self.presentation_visible:
                return
            controls = self.query_one_optional("#sidebar-controls")
            if controls is not None:
                await controls.mount_all(self._compose_controls())
            if self.is_attached and not self.is_leaving and self.presentation_visible:
                self._panels_loaded = True
                self._presented_layout = None
                await self.panels_hydrated()
                self.restore_navigation()
        finally:
            self._panels_ready.set()

    async def panels_hydrated(self) -> None:
        """The sidebar declaration completes its panel preparation."""

    async def wait_content_ready(self) -> None:
        await self._panels_ready.wait()

    def on_unmount(self) -> None:
        self._panels_ready.set()

    def compose(self) -> ComposeResult:
        yield SideBarToggle(self.collapsed, right=self.right)
        yield SidebarResizeHandle()
        yield self.search_input
        with self.panels_viewport:
            if self._panels_loaded:
                yield from self._compose_panels()
        with containers.Vertical(id="sidebar-controls"):
            if self._panels_loaded:
                yield from self._compose_controls()

    @on(widgets.Input.Changed)
    def search_changed(self, event: widgets.Input.Changed) -> None:
        if event.input is self.search_input:
            event.stop()
            self.search = event.value

    def _compose_panels(self) -> ComposeResult:
        navigation = self.navigation
        for panel in self.panels:
            yield SideBarCollapsible(
                panel.widget,
                title=panel.title,
                collapsed=navigation.panels_collapsed.get(panel.title, panel.collapsed),
                classes="-flex" if panel.flex else "-fixed",
                id=panel.id,
                header_control=panel.header_control,
            )

    def _compose_controls(self) -> ComposeResult:
        yield self.width_slider
        yield containers.Grid(
            *(
                SidebarAction(kind())
                for kind in SidebarPlacementAction.members_with(SidebarPlacementAction)
            ),
            id="sidebar-layout-actions",
        )

    def on_resize(self, event: events.Resize) -> None:
        self._present_controls()

    def on_show(self) -> None:
        self._present_controls()

    def _present_controls(self) -> bool:
        app = self.app
        if not self.is_mounted:
            return False
        placement = app.sidebar_layout.get(self.id)
        if self.parent is None or not self.presentation_visible:
            self._presented_layout = None
            return False
        geometry = SidebarGeometry(self.region.x, self.size.width)
        width = geometry.width
        directions = app.sidebar_layout.directions(self.id)
        current = PresentedBar(
            presentation=BarPresentation.from_placement(
                placement, collapsed=self.collapsed, directions=directions, width=width
            ),
            geometry=geometry,
            width_percent=placement.width_percent,
        )
        previous = self._presented_layout
        if current == previous:
            return False
        self._presented_layout = current
        controls = (
            self.query_one_optional("#sidebar-controls")
            if self._panels_loaded
            else None
        )
        slider = self.width_slider
        if previous is None or previous.presentation != current.presentation:
            self.right = placement.side == "right"
            self.set_class(self.right, "-right")
            self.search_input.styles.margin = (
                (0, 0, 0, 4) if self.right else (0, 4, 0, 0)
            )
            if toggle := self.query_one_optional(SideBarToggle):
                toggle.right = self.right
                toggle.set_collapsed(self.collapsed)
            if handle := self.query_one_optional(SidebarResizeHandle):
                handle.display = not self.collapsed
            if controls is not None:
                controls.display = not self.collapsed
                actions = controls.query_one_optional("#sidebar-layout-actions")
                buttons = {
                    direction: controls.query_one_optional(
                        f"#sidebar-{direction}", SidebarAction
                    )
                    for direction in (*directions, "float")
                }
                if actions is None or any(
                    button is None for button in buttons.values()
                ):
                    # Mounted parents can precede their composed action rows.
                    self._presented_layout = None
                else:
                    slider.reversed = self.right
                    slider.set_range(15, 50, placement.width_percent)
                    for direction, action in directions.items():
                        button = buttons[direction]
                        button.display = action.available
                        button.tooltip = action.tooltip(direction)
                    toggle_mode = buttons["float"]
                    toggle_mode.update(
                        "Push" if placement.floating else "Float", layout=False
                    )
                    toggle_mode.tooltip = (
                        "Push conversation text"
                        if placement.floating
                        else "Float over conversation text"
                    )
                    actions.set_class(current.presentation.compact, "-compact")
        if slider.value != placement.width_percent:
            slider.value = placement.width_percent
            slider.refresh()
        return True

    @on(SidebarSlider.Changed)
    def on_sidebar_slider(self, event: SidebarSlider.Changed) -> None:
        event.stop()
        if self.id is not None:
            app = self.app
            if app.sidebar_layout.width(self.id, event.value):
                self._present_controls()
                app.workspace_chrome.refresh_layout()

    @on(SidebarAction.Pressed)
    def on_sidebar_action(self, event: SidebarAction.Pressed) -> None:
        event.stop()
        if self.id is None:
            return
        app = self.app
        event.action.apply(app.sidebar_layout, self.id)
        for bar in (
            app.workspace_chrome.channels,
            *app.workspace_sessions.source.sidebars(),
        ):
            bar._present_controls()
        app.workspace_chrome.refresh_layout()

    def restore_navigation(self) -> bool:
        changed = self._presented_collapsed != self.collapsed
        if changed:
            self.watch_collapsed(self.collapsed)
        else:
            self._present_controls()
            self.app.workspace_chrome.refresh_layout()
        navigation = self.navigation
        for panel in self.query(SideBarCollapsible):
            if str(panel.title) in navigation.panels_collapsed:
                panel.collapsed = navigation.panels_collapsed[str(panel.title)]
        return changed

    def watch_collapsed(self, collapsed: bool) -> None:
        if self.is_mounted and not self.presentation_visible:
            # Keep shared intent current without resizing every hidden transcript.
            # Activation applies the latest value inside its render transaction;
            # an open/close round trip can therefore keep unchanged geometry.
            return
        if not collapsed and self.is_mounted:
            self.schedule_hydration()
        self._presented_collapsed = collapsed
        # Panel visibility is independent of its native placement.
        self.panels_viewport.display = not collapsed
        self.search_input.display = not collapsed
        if controls := self.query_one_optional("#sidebar-controls"):
            controls.display = not collapsed
        self.tooltip = "Expand sidebar" if collapsed else None
        toggle = self.query_one_optional(SideBarToggle)
        if toggle is not None:
            toggle.set_collapsed(collapsed)
            toggle.refresh_paint()
        for panel in self.panels:
            panel.widget.sidebar_visibility_changed()
        self._presented_layout = None
        if self.is_mounted:
            self._present_controls()
            self.app.workspace_chrome.refresh_layout()

    def render(self) -> str:
        return ("<" if self.right else ">") if self.collapsed else ""

    @handles(PreferenceChanged)
    async def _settings_changed(self, event: PreferenceChanged) -> None:
        if SETTINGS.sidebar.hide.matches(event.field):
            self.collapsed = event.field.value

    @on(SideBarToggle.Pressed)
    def on_toggle_pressed(self, event: SideBarToggle.Pressed) -> None:
        event.stop()
        self.toggle(focus=event.focus)

    def on_click(self, event: Click) -> None:
        if self.collapsed and event.button == 1:
            event.stop()
            self.toggle(focus=False)

    @on(events.Enter)
    @on(events.Leave)
    def gutter_hover_changed(self) -> None:
        self.query_one(SideBarToggle).refresh_paint()

    def toggle(self, *, focus: bool = True) -> None:
        collapsed = not self.collapsed
        return_focus = collapsed and (focus or self.has_focus_within)
        if return_focus and self.is_mounted and self.screen.is_current:
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
            if title := self.query_one_optional("SideBarCollapsible CollapsibleTitle"):
                title.focus()
            else:
                self.schedule_hydration()

    def reveal(self) -> None:
        self.store_collapsed(False)

    def dismiss_control(self) -> None:
        if SETTINGS.sidebar.hide.bind(self.app.saved_settings.state).value:
            self.collapsed = True
        self.post_message(self.Dismiss())


class ThreadSidebar(SideBar):
    def __init__(self, *panels, state: SidebarState, **kwargs):
        self.state = state
        super().__init__(*panels, id="thread-sidebar", right=True, hide=True, **kwargs)
        self.collapsed = self.hide

    @property
    def navigation(self) -> SidebarState:
        return self.state

    def mount_collapse(self) -> None:
        self.collapsed = self.hide

    def store_collapsed(self, value: bool) -> None:
        self.collapsed = value
