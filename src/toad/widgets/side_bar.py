from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from textual import containers, events, on, widgets
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Click
from textual.geometry import Offset
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from toad.session_tracker import SidebarState

if TYPE_CHECKING:
    from toad.app import ToadApp


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
        width: 1fr;
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
        height: 1fr;
        min-height: 12;
    }
    SideBarCollapsible.-flex > Contents {
        height: 1fr;
        overflow-y: auto;
        scrollbar-gutter: stable;
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

    def compose(self) -> ComposeResult:
        if self.header_control is None:
            yield from super().compose()
        else:
            with containers.HorizontalGroup(classes="sidebar-header"):
                yield self._title
                yield self.header_control
            with self.Contents():
                yield from self._contents_list


class SideBarToggle(widgets.Static):
    """Full-height pointer target in the sidebar's left gutter."""

    DEFAULT_CSS = """
    SideBarToggle {
        dock: left;
        width: 3;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        background: $primary 8%;
        layer: sidebar-toggle;
    }
    SideBarToggle:hover,
    SideBarToggle:focus {
        color: $text;
        background: $primary 18%;
        text-style: bold;
    }
    SideBarToggle:ansi {
        color: ansi_white;
        background: ansi_black;
    }
    SideBarToggle:ansi:hover,
    SideBarToggle:ansi:focus,
    SideBarToggle:ansi.-gutter-hover {
        color: ansi_white;
        background: ansi_bright_black;
    }
    SideBarToggle.-gutter-hover {
        color: $text;
        background: $primary 18%;
        text-style: bold;
    }
    """

    can_focus = True
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "sidebar_toggle", "Toggle sidebar", show=False)
    ]

    class Pressed(Message):
        pass

    def __init__(self, collapsed: bool = False, *, right: bool = False) -> None:
        super().__init__()
        self.right = right
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self.update(
            ("<" if collapsed else ">") if self.right else (">" if collapsed else "<"),
            layout=False,
        )
        self.tooltip = "Expand sidebar" if collapsed else "Collapse sidebar"

    def action_sidebar_toggle(self) -> None:
        self.post_message(self.Pressed())

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_sidebar_toggle()


class TabHistoryButton(widgets.Static, can_focus=True):
    """One compact, keyboard-accessible tab-history control."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "navigate", "Navigate tab", show=False)
    ]
    DEFAULT_CSS = """
    TabHistoryButton {
        width: 7;
        height: 3;
        content-align: center middle;
        color: $text;
        background: $background;
        text-style: bold;
        pointer: pointer;
    }
    TabHistoryButton:hover, TabHistoryButton:focus {
        color: $background;
        background: $foreground 80%;
        text-style: bold;
    }
    TabHistoryButton.-unavailable {
        color: $text-muted 40%;
        pointer: default;
    }
    TabHistoryButton.-unavailable:hover, TabHistoryButton.-unavailable:focus {
        color: $background;
        background: $foreground 80%;
    }
    TabHistoryButton:ansi {
        color: ansi_white;
        background: ansi_black;
    }
    TabHistoryButton:ansi:hover, TabHistoryButton:ansi:focus {
        color: ansi_black;
        background: ansi_white;
    }
    TabHistoryButton.-unavailable:ansi {
        color: ansi_bright_black;
        background: ansi_black;
    }
    TabHistoryButton.-unavailable:ansi:hover,
    TabHistoryButton.-unavailable:ansi:focus {
        color: ansi_black;
        background: ansi_white;
    }
    """

    def __init__(self, direction: int) -> None:
        super().__init__("<──" if direction == -1 else "──>",
                         id="tab-back" if direction == -1 else "tab-forward")
        self.direction = direction
        self.tooltip = ("Back through visited tabs" if direction == -1
                        else "Forward through visited tabs")

    def action_navigate(self) -> None:
        if not self.has_class("-unavailable"):
            cast("ToadApp", self.app).navigate_tab_history(self.direction)

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_navigate()


class MainMenuButton(widgets.Static, can_focus=True):
    """Open Toad's existing anchored menu beside the tab-history controls."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "open_menu", "Main menu", show=False)
    ]
    DEFAULT_CSS = """
    MainMenuButton {
        width: 7;
        height: 3;
        content-align: center middle;
        color: $text;
        background: $background;
        text-style: bold;
        pointer: pointer;
    }
    MainMenuButton:hover, MainMenuButton:focus {
        color: $background;
        background: $foreground 80%;
    }
    MainMenuButton:ansi { color: ansi_white; background: ansi_black; }
    MainMenuButton:ansi:hover, MainMenuButton:ansi:focus {
        color: ansi_black;
        background: ansi_white;
    }
    """

    class Pressed(Message):
        pass

    def __init__(self) -> None:
        super().__init__("☰", id="main-menu")
        self.tooltip = "Main menu: export wire or import thread"

    def action_open_menu(self) -> None:
        self.post_message(self.Pressed())

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_open_menu()


class TabHistoryControls(containers.HorizontalGroup):
    """Left-sidebar controls shared by native thread and channel screens."""

    DEFAULT_CSS = """
    TabHistoryControls {
        width: auto;
        height: 3;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield MainMenuButton()
        yield TabHistoryButton(-1)
        yield TabHistoryButton(+1)

    @on(MainMenuButton.Pressed)
    def on_main_menu_pressed(self, event: MainMenuButton.Pressed) -> None:
        from toad.widgets.comms_menu import show_target_menu

        event.stop()
        button = self.query_one(MainMenuButton)
        show_target_menu(
            self.screen,
            Offset(button.region.x, button.region.y + button.size.height),
            "Toad",
            [("export", "Export wire history…"), ("import", "Thread Import…")],
            {
                "export": cast("ToadApp", self.app).open_wire_export_dialog,
                "import": cast("ToadApp", self.app).open_thread_import_dialog,
            },
        )

    def on_mount(self) -> None:
        app = cast("ToadApp", self.app)
        app.tab_history_changed.subscribe(self, self._sync)
        app.open_tabs_changed.subscribe(self, self._sync)
        self._sync(None)

    def _sync(self, _event: None) -> None:
        app = cast("ToadApp", self.app)
        for button in self.query(TabHistoryButton):
            unavailable = not app.can_navigate_tab_history(button.direction)
            button.set_class(unavailable, "-unavailable")
            button.tooltip = (
                "No earlier visited tab" if button.direction == -1 else "No later visited tab"
            ) if unavailable else (
                "Back through visited tabs" if button.direction == -1
                else "Forward through visited tabs"
            )


class SidebarSlider(widgets.Static, can_focus=True):
    """A bottom-row pointer/keyboard slider; no polling or source snapshots."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "step(-1)", "Decrease", show=False),
        Binding("right", "step(1)", "Increase", show=False),
    ]
    DEFAULT_CSS = """
    SidebarSlider { height: 1; width: 1fr; color: $text-muted; pointer: pointer; }
    SidebarSlider:hover, SidebarSlider:focus { color: $accent; }
    """

    @dataclass
    class Changed(Message):
        slider: SidebarSlider
        value: int

    def __init__(self, kind: str, minimum: int, maximum: int, value: int) -> None:
        super().__init__(id=f"sidebar-{kind}-slider")
        self.kind = kind
        self.minimum = minimum
        self.maximum = maximum
        self.value = value
        self._dragging = False
        self.tooltip = ("Drag or use ←/→ to resize (15–50% of screen)" if kind == "width"
                        else "Drag or use ←/→ to reveal long sidebar rows")

    def set_range(self, minimum: int, maximum: int, value: int) -> None:
        self.minimum, self.maximum = minimum, max(minimum, maximum)
        self.value = max(self.minimum, min(self.maximum, value))
        self.refresh()

    def render(self) -> str:
        label = f"{self.value:2d}%" if self.kind == "width" else "↔"
        track = max(1, self.size.width - len(label) - 1)
        ratio = (self.value - self.minimum) / max(1, self.maximum - self.minimum)
        thumb = round(ratio * (track - 1))
        return f"{label} " + "".join("●" if index == thumb else "─" for index in range(track))

    def _choose(self, x: int) -> None:
        label_width = 4 if self.kind == "width" else 2
        track = max(1, self.size.width - label_width)
        ratio = max(0.0, min(1.0, (x - label_width) / max(1, track - 1)))
        value = round(self.minimum + ratio * (self.maximum - self.minimum))
        if value != self.value:
            self.value = value
            self.refresh()
            self.post_message(self.Changed(self, value))

    def action_step(self, direction: int) -> None:
        step = 1 if self.kind == "width" else max(1, self.maximum // 30)
        value = max(self.minimum, min(self.maximum, self.value + direction * step))
        if value != self.value:
            self.value = value
            self.refresh()
            self.post_message(self.Changed(self, value))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button == 1:
            event.stop()
            self._dragging = True
            self.capture_mouse()
            self._choose(event.x)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging:
            event.stop()
            self._choose(event.x)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button == 1 and self._dragging:
            event.stop()
            self._choose(event.x)
            self._dragging = False
            self.release_mouse()


class SidebarAction(widgets.Static, can_focus=True):
    """One explicit move, same-edge swap or float/push action."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "activate", "Sidebar layout", show=False)
    ]
    DEFAULT_CSS = """
    SidebarAction { height: 1; width: auto; padding: 0 1; color: $text-muted; pointer: pointer; }
    SidebarAction:hover, SidebarAction:focus {
        color: $background; background: $foreground 80%;
    }
    """

    @dataclass
    class Pressed(Message):
        action: str

    def __init__(self, action: str, label: str) -> None:
        super().__init__(label, id=f"sidebar-{action}")
        self.action = action

    def action_activate(self) -> None:
        self.post_message(self.Pressed(self.action))

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_activate()


class SideBar(containers.Vertical):
    BINDING_GROUP_TITLE = "Sidebar"
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Dismiss sidebar")]
    DEFAULT_CSS = """
    SideBar {
        layers: sidebar-content sidebar-toggle;
        background: transparent;
        dock: left;
        overflow: hidden;
        scrollbar-size: 0 0;
        height: 1fr;
        width: 40;
        min-width: 40;
        max-width: 45%;
        border-right: tall $primary 30%;
    }
    SideBar:ansi {
        border-right: tall ansi_bright_black;
    }
    SideBar > #sidebar-panels {
        width: 1fr;
        height: 1fr;
        margin-left: 3;
        layer: sidebar-content;
        overflow-y: auto;
        scrollbar-size: 1 1;
        scrollbar-gutter: stable;
    }
    SideBar > #sidebar-controls {
        width: 1fr;
        height: 3;
        margin-left: 3;
        layer: sidebar-content;
        background: $background;
    }
    SideBar #sidebar-layout-actions { height: 1; width: 1fr; }
    SideBar.-right {
        dock: right;
        width: 34;
        min-width: 28;
        border-right: none;
        border-left: tall $primary 30%;
    }
    SideBar.-right > SideBarToggle { dock: right; }
    SideBar.-right > #sidebar-panels { margin-left: 0; margin-right: 3; }
    SideBar.-right > #sidebar-controls { margin-left: 0; margin-right: 3; }
    """

    collapsed = reactive(False)

    class Dismiss(Message):
        pass

    @dataclass(frozen=True)
    class Panel:
        title: str
        widget: Widget
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
        navigation: SidebarState | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.panels: list[SideBar.Panel] = [*panels]
        self.hide = hide
        self.right = right
        self._navigation = navigation
        self._presented_collapsed: bool | None = None
        self._presented_layout: tuple | None = None
        self.set_class(right, "-right")
        if navigation is not None:
            self.collapsed = hide

    @property
    def navigation(self) -> SidebarState:
        return (self._navigation if self._navigation is not None
                else cast("ToadApp", self.app).sidebar_state)

    def on_mount(self) -> None:
        self.trap_focus()
        app = cast("ToadApp", self.app)
        if self.id in app.sidebar_layout.placements:
            app.sidebar_layout_changed.subscribe(self, self._layout_changed)
        if self._navigation is None:
            cast("ToadApp", self.app).settings_changed_signal.subscribe(
                self, self._settings_changed  # type: ignore[arg-type]
            )
            self.collapsed = cast("ToadApp", self.app).settings.get("sidebar.hide", bool)
        else:
            self.collapsed = self.hide
        self.watch_collapsed(self.collapsed)
        self._apply_layout()

    def compose(self) -> ComposeResult:
        yield SideBarToggle(self.collapsed, right=self.right)
        navigation = self.navigation
        with containers.VerticalScroll(id="sidebar-panels"):
            for panel in self.panels:
                yield SideBarCollapsible(
                    panel.widget,
                    title=panel.title,
                    collapsed=navigation.panels_collapsed.get(panel.title, panel.collapsed),
                    classes="-flex" if panel.flex else "-fixed",
                    id=panel.id,
                    header_control=panel.header_control,
                )
        if self.id in {"channels-sidebar", "thread-sidebar"}:
            with containers.Vertical(id="sidebar-controls"):
                yield SidebarSlider("width", 15, 50, 40 if not self.right else 34)
                with containers.Horizontal(id="sidebar-layout-actions"):
                    yield SidebarAction("move", "→" if not self.right else "←")
                    yield SidebarAction("swap", "⇄")
                    yield SidebarAction("float", "Float")
                yield SidebarSlider("horizontal", 0, 0, 0)

    def _order_sidebars(self) -> None:
        parent = self.parent
        if parent is None:
            return
        app = cast("ToadApp", self.app)
        order = {key: index for index, key in enumerate(app.sidebar_layout.ordered())}
        before = tuple(child.id for child in parent.children)
        after = tuple(sorted(before, key=lambda identity: order.get(identity, len(order))))
        if before != after:
            parent.sort_children(key=lambda child: order.get(child.id, len(order)))
            parent.refresh(layout=True)

    def _content_gutters(self) -> None:
        """Same-edge docks overlap natively; reserve only their missing gutter."""
        parent = self.parent
        if parent is None:
            return
        siblings = [child for child in parent.children if isinstance(child, SideBar)]
        content = next((child for child in parent.children if not isinstance(child, SideBar)), None)
        if content is None:
            return
        app = cast("ToadApp", self.app)
        extra: dict[str, int] = {}
        for side in ("left", "right"):
            widths = [int(bar.styles.width.value)
                      for bar in siblings if bar.id in app.sidebar_layout.placements
                      and app.sidebar_layout.get(bar.id).side == side
                      and (bar.collapsed or not app.sidebar_layout.get(bar.id).floating)]
            extra[side] = sum(widths) - max(widths) if widths else 0
        content.styles.margin = (0, extra["right"], 0, extra["left"])

    def _apply_layout(self) -> bool:
        app = cast("ToadApp", self.app)
        if self.id not in app.sidebar_layout.placements or not self.is_mounted:
            return False
        placement = app.sidebar_layout.get(self.id)
        other = next((sidebar for sidebar in self.parent.query(SideBar)
                      if sidebar is not self and sidebar.parent is self.parent), None)
        peer = app.sidebar_layout.get(other.id) if other is not None else None
        viewport = max(1, app.size.width)
        peer_width = (0 if peer is None or peer.floating else
                      3 if other.collapsed else max(18, viewport * peer.width_percent // 100))
        width = max(18, min(viewport // 2, viewport * placement.width_percent // 100,
                            max(18, viewport - 24 - peer_width)))
        key = (placement, width, viewport, peer_width, self.collapsed)
        if key == self._presented_layout:
            return False
        self._presented_layout = key
        self.right = placement.side == "right"
        self.set_class(self.right, "-right")
        if toggle := self.query_one_optional(SideBarToggle):
            toggle.right = self.right
            toggle.set_collapsed(self.collapsed)
        self.styles.width = 3 if self.collapsed else width
        self.styles.min_width = 3 if self.collapsed else min(18, width)
        self.styles.max_width = 3 if self.collapsed else width
        if placement.floating and not self.collapsed:
            self.styles.dock = "none"
            self.styles.position = "absolute"
            self.styles.overlay = "screen"
            if placement.side == "left":
                outer = (max(18, viewport * peer.width_percent // 100)
                         if peer and peer.side == "left" and placement.order == 1 else 0)
                self.offset = (outer, 0)
            else:
                outer = (max(18, viewport * peer.width_percent // 100)
                         if peer and peer.side == "right" and placement.order == 1 else 0)
                self.offset = (max(0, viewport - outer - width), 0)
        else:
            self.styles.dock = placement.side
            self.styles.position = None
            self.styles.overlay = None
            outer_width = (
                3 if other.collapsed else
                max(18, min(viewport // 2, viewport * peer.width_percent // 100))
            ) if peer and peer.side == placement.side and placement.order == 1 else 0
            self.offset = (outer_width if placement.side == "left" else -outer_width, 0)
        if controls := self.query_one_optional("#sidebar-controls"):
            controls.display = not self.collapsed
            controls.query_one("#sidebar-width-slider", SidebarSlider).set_range(
                15, 50, placement.width_percent
            )
            move = controls.query_one("#sidebar-move", SidebarAction)
            move.update("→" if placement.side == "left" else "←", layout=False)
            move.tooltip = f"Move {self.id} to the opposite side"
            controls.query_one("#sidebar-swap", SidebarAction).display = (
                peer is not None and peer.side == placement.side
            )
            toggle_mode = controls.query_one("#sidebar-float", SidebarAction)
            toggle_mode.update("Push" if placement.floating else "Float", layout=False)
        self._content_gutters()
        return True

    def _layout_changed(self, _update: None) -> None:
        if self.is_mounted and self.screen.is_current and self._apply_layout():
            self._order_sidebars()

    def on_resize(self) -> None:
        if self.is_mounted and self.screen.is_current and self._apply_layout():
            cast("ToadApp", self.app).sidebar_layout_changed.publish(None)

    @on(SidebarSlider.Changed)
    def on_sidebar_slider(self, event: SidebarSlider.Changed) -> None:
        event.stop()
        if event.slider.kind == "width" and self.id is not None:
            app = cast("ToadApp", self.app)
            if app.sidebar_layout.width(self.id, event.value):
                app.sidebar_layout_changed.publish(None)
        elif event.slider.kind == "horizontal":
            self.scroll_horizontally(event.value)

    @on(SidebarAction.Pressed)
    def on_sidebar_action(self, event: SidebarAction.Pressed) -> None:
        event.stop()
        if self.id is None:
            return
        app = cast("ToadApp", self.app)
        placement = app.sidebar_layout.get(self.id)
        if event.action == "move":
            app.sidebar_layout.move(self.id, "right" if placement.side == "left" else "left")
        elif event.action == "swap":
            app.sidebar_layout.swap(self.id)
        elif event.action == "float":
            app.sidebar_layout.float_mode(self.id)
        app.sidebar_layout_changed.publish(None)

    def scroll_horizontally(self, offset: int) -> None:
        from toad.widgets.virtual_channel_list import VirtualChannelList

        if listing := self.query_one_optional(VirtualChannelList):
            listing.set_horizontal_offset(offset)
        else:
            self.query_one("#sidebar-panels", containers.VerticalScroll).scroll_to(
                x=offset, animate=False, immediate=True
            )
        self._sync_horizontal_slider()

    def _sync_horizontal_slider(self) -> None:
        from toad.widgets.virtual_channel_list import VirtualChannelList

        slider = self.query_one_optional("#sidebar-horizontal-slider", SidebarSlider)
        if slider is None:
            return
        if listing := self.query_one_optional(VirtualChannelList):
            slider.set_range(0, listing.horizontal_max, listing.horizontal_offset)
        else:
            panels = self.query_one("#sidebar-panels", containers.VerticalScroll)
            slider.set_range(0, int(panels.max_scroll_x), int(panels.scroll_x))

    @on(widgets.Collapsible.Collapsed)
    @on(widgets.Collapsible.Expanded)
    def panel_toggled(self, event: widgets.Collapsible.Toggled) -> None:
        panel = event.collapsible
        if isinstance(panel, SideBarCollapsible):
            self.navigation.panels_collapsed[str(panel.title)] = panel.collapsed

    def restore_navigation(self) -> bool:
        changed = self._presented_collapsed != self.collapsed
        if changed:
            self.watch_collapsed(self.collapsed)
        changed |= self._apply_layout()
        navigation = self.navigation
        for panel in self.query(SideBarCollapsible):
            if str(panel.title) in navigation.panels_collapsed:
                panel.collapsed = navigation.panels_collapsed[str(panel.title)]
        return changed

    def watch_collapsed(self, collapsed: bool) -> None:
        if self._navigation is None and self.is_mounted and not self.screen.is_current:
            # Keep shared intent current without resizing every hidden transcript.
            # Activation applies the latest value inside its render transaction;
            # an open/close round trip can therefore keep unchanged geometry.
            return
        self._presented_collapsed = collapsed
        # The old -collapsed ancestor selector restyled every descendant row
        # (hundreds of expensive stylesheet.apply calls per toggle). Inline
        # box changes affect only this sidebar and its immediate panels.
        self.styles.width = 3 if collapsed else None
        self.styles.min_width = 3 if collapsed else None
        self.styles.max_width = 3 if collapsed else None
        if self.right:
            self.styles.border_left = ("none", "transparent") if collapsed else None
        else:
            self.styles.border_right = ("none", "transparent") if collapsed else None
        if panels := self.query_one_optional("#sidebar-panels"):
            panels.display = not collapsed
        if controls := self.query_one_optional("#sidebar-controls"):
            controls.display = not collapsed
        self.tooltip = "Expand sidebar" if collapsed else None
        toggle = self.query_one_optional(SideBarToggle)
        if toggle is not None:
            toggle.set_collapsed(collapsed)
            if not collapsed:
                toggle.remove_class("-gutter-hover")
        from toad.widgets.comms_sidebar import CommsSidebar

        for sidebar in self.query(CommsSidebar):
            sidebar._sync_spinner()
        from toad.widgets.thread_comms import ThreadCommsSidebar

        for tree in self.query(ThreadCommsSidebar):
            tree._sync_spinner()
        self._presented_layout = None
        if self.is_mounted and self.id in cast("ToadApp", self.app).sidebar_layout.placements:
            self._apply_layout()
            cast("ToadApp", self.app).sidebar_layout_changed.publish(None)

    def render(self) -> str:
        return ("<" if self.right else ">") if self.collapsed else ""

    def _settings_changed(self, update: tuple[str, object]) -> None:
        key, value = update
        if key == "sidebar.hide":
            self.collapsed = bool(value)

    @on(SideBarToggle.Pressed)
    def on_toggle_pressed(self, event: SideBarToggle.Pressed) -> None:
        event.stop()
        self.toggle()

    def on_click(self, event: Click) -> None:
        if self.collapsed and event.button == 1:
            event.stop()
            self.toggle()

    def on_enter(self) -> None:
        if self.collapsed:
            self.query_one(SideBarToggle).add_class("-gutter-hover")

    def on_leave(self) -> None:
        if toggle := self.query_one_optional(SideBarToggle):
            toggle.remove_class("-gutter-hover")

    def toggle(self) -> None:
        collapsed = not self.collapsed
        if self._navigation is None:
            cast("ToadApp", self.app).settings.set("sidebar.hide", collapsed)
        else:
            self.collapsed = collapsed
        if collapsed:
            self.post_message(self.Dismiss())
        else:
            # Panels are already displayed by the synchronous watcher. Queue
            # native focus now so its highlight can share the opening frame,
            # rather than waiting for a painted frame to request another one.
            self.query_one("SideBarCollapsible CollapsibleTitle").focus()

    def reveal(self) -> None:
        if self._navigation is None:
            cast("ToadApp", self.app).settings.set("sidebar.hide", False)
        else:
            self.collapsed = False

    def action_dismiss(self) -> None:
        if cast("ToadApp", self.app).settings.get("sidebar.hide", bool):
            self.collapsed = True
        self.post_message(self.Dismiss())


if __name__ == "__main__":
    from textual.app import App, ComposeResult

    class SApp(App):
        def compose(self) -> ComposeResult:
            yield SideBar(
                SideBar.Panel("Hello", widgets.Label("Hello, World!")),
                SideBar.Panel(
                    "Files",
                    widgets.DirectoryTree(
                        "~/",
                    ),
                    flex=True,
                ),
                SideBar.Panel(
                    "Hello",
                    widgets.Static("Where there is a Will! " * 10),
                ),
            )

    SApp().run()
