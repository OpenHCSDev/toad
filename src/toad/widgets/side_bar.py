from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from textual import containers, on, widgets
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
    SideBar.-right {
        dock: right;
        width: 34;
        min-width: 28;
        border-right: none;
        border-left: tall $primary 30%;
    }
    SideBar.-right > SideBarToggle { dock: right; }
    SideBar.-right > #sidebar-panels { margin-left: 0; margin-right: 3; }
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
        self.set_class(right, "-right")
        if navigation is not None:
            self.collapsed = hide

    @property
    def navigation(self) -> SidebarState:
        return (self._navigation if self._navigation is not None
                else cast("ToadApp", self.app).sidebar_state)

    def on_mount(self) -> None:
        self.trap_focus()
        if self._navigation is None:
            cast("ToadApp", self.app).settings_changed_signal.subscribe(
                self, self._settings_changed  # type: ignore[arg-type]
            )
            self.collapsed = cast("ToadApp", self.app).settings.get("sidebar.hide", bool)
        else:
            self.collapsed = self.hide
        self.watch_collapsed(self.collapsed)

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
        self.tooltip = "Expand sidebar" if collapsed else None
        toggle = self.query_one_optional(SideBarToggle)
        if toggle is not None:
            toggle.set_collapsed(collapsed)
            if not collapsed:
                toggle.remove_class("-gutter-hover")

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
