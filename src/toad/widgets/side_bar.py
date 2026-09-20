from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from textual import containers, on, widgets
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

if TYPE_CHECKING:
    from toad.app import ToadApp


class SideBarCollapsible(widgets.Collapsible):
    BINDING_GROUP_TITLE = "Sidebar collapsible"
    HELP = """\
## Sidebar

This is your sidebar.

The Sidebar contains additonal information associated with the conversation.

- **tab / shift+tab** Navigate sections
- **enter** expand or collapse secions
"""

    DEFAULT_CSS = """
    SideBarCollapsible {
        width: 1fr;
        height: auto;
        min-height: 1;
        padding: 0;
        border-top: none;
        background: transparent;
    }
    SideBarCollapsible > CollapsibleTitle {
        width: 1fr;
        padding: 0;
    }
    SideBarCollapsible > Contents {
        height: auto;
        padding: 0;
    }
    SideBarCollapsible.-flex {
        height: 80%;
        min-height: 12;
    }
    SideBarCollapsible.-flex > Contents {
        height: 1fr;
    }
    """


class SideBarToggle(widgets.Static):
    """Full-height pointer target in the sidebar's left gutter."""

    DEFAULT_CSS = """
    SideBarToggle {
        dock: left;
        width: 1;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
        background: $primary 12%;
        layer: sidebar-toggle;
    }
    SideBarToggle:hover,
    SideBarToggle:focus {
        color: $text;
        background: $primary 35%;
        text-style: bold;
    }
    SideBarToggle:ansi:hover,
    SideBarToggle:ansi:focus {
        color: ansi_black;
        background: ansi_bright_white;
    }
    """

    can_focus = True
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "sidebar_toggle", "Toggle sidebar", show=False)
    ]

    class Pressed(Message):
        pass

    def __init__(self, collapsed: bool = False) -> None:
        super().__init__()
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self.update(">" if collapsed else "<")
        self.tooltip = "Expand sidebar" if collapsed else "Collapse sidebar"

    def action_sidebar_toggle(self) -> None:
        self.post_message(self.Pressed())

    def on_click(self, event: Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_sidebar_toggle()


class SideBar(containers.Vertical):
    BINDING_GROUP_TITLE = "Sidebar"
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Dismiss sidebar")]
    DEFAULT_CSS = """
    SideBar {
        layers: sidebar-content sidebar-toggle;
    }
    SideBar > #sidebar-panels {
        width: 1fr;
        height: 1fr;
        margin-left: 1;
        layer: sidebar-content;
        overflow-y: auto;
        scrollbar-size: 1 1;
    }
    SideBar.-collapsed {
        width: 1;
        min-width: 1;
        max-width: 1;
        border-right: none;
        overflow: hidden;
        content-align: center middle;
        color: $text-muted;
        background: $primary 12%;
    }
    SideBar.-collapsed.-gutter-hover {
        background: $text;
        color: $background;
    }
    SideBar.-collapsed > #sidebar-panels {
        display: none;
    }
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

    def __init__(
        self,
        *panels: Panel,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        hide: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.panels: list[SideBar.Panel] = [*panels]
        self.hide = hide

    def on_mount(self) -> None:
        self.trap_focus()
        cast("ToadApp", self.app).settings_changed_signal.subscribe(
            self, self._settings_changed  # type: ignore[arg-type]
        )
        self.collapsed = self.app.has_class("-hide-sidebar")

    def compose(self) -> ComposeResult:
        yield SideBarToggle(self.collapsed)
        with containers.VerticalScroll(id="sidebar-panels"):
            for panel in self.panels:
                yield SideBarCollapsible(
                    panel.widget,
                    title=panel.title,
                    collapsed=panel.collapsed,
                    classes="-flex" if panel.flex else "-fixed",
                    id=panel.id,
                )

    def watch_collapsed(self, collapsed: bool) -> None:
        self.set_class(collapsed, "-collapsed")
        if not collapsed:
            self.remove_class("-gutter-hover")
            self.styles.background = None
            self.styles.color = None
        self.tooltip = "Expand sidebar" if collapsed else None
        toggle = self.query_one_optional(SideBarToggle)
        if toggle is not None:
            toggle.set_collapsed(collapsed)

    def render(self) -> str:
        return ">" if self.collapsed else ""

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
            self.add_class("-gutter-hover")
            variables = self.app.get_css_variables()
            self.styles.background = variables["text"]
            self.styles.color = variables["background"]

    def on_leave(self) -> None:
        self.remove_class("-gutter-hover")
        self.styles.background = None
        self.styles.color = None

    def toggle(self) -> None:
        collapsed = not self.collapsed
        cast("ToadApp", self.app).settings.set("sidebar.hide", collapsed)
        if collapsed:
            self.post_message(self.Dismiss())
        else:
            self.call_after_refresh(
                self.query_one("Collapsible CollapsibleTitle").focus
            )

    def reveal(self) -> None:
        cast("ToadApp", self.app).settings.set("sidebar.hide", False)

    def action_dismiss(self) -> None:
        if self.app.has_class("-hide-sidebar"):
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
