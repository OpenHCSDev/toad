from functools import partial
from rich.style import Style as RichStyle

from textual.app import ComposeResult, RenderResult

from textual import events
from textual.content import Content
from textual.geometry import Offset
from textual.reactive import reactive
from textual.renderables.bar import Bar
from textual.widget import Widget
from textual import containers
from textual import widgets
from textual import getters
from textual.message import Message

from toad.app import ToadApp
from toad.session_tracker import SessionDetails, OpenTab
from toad import messages


class SessionLabel(widgets.Label):
    ALLOW_SELECT = False

    def on_click(self, event: events.Click) -> None:
        if self.id is not None:
            if event.button == 2:
                event.stop()
                self.app.post_message(messages.SessionArchive(self.id))
            elif event.button == 1:
                # A second message-pump hop lets the old screen's pending
                # full-layout timer run ahead of the user's tab click. The
                # ordinary app mode-switch boundary already captures sidebar
                # navigation and queues its serialized transition.
                self.app.switch_mode(self.id)


class SessionTabClose(widgets.Static, can_focus=True):
    """Close a tab without selecting it or deleting its saved thread."""

    ALLOW_SELECT = False
    BINDINGS = [("enter,space", "close_tab", "Close tab")]
    DEFAULT_CSS = """
    SessionTabClose {
        width: 2;
        height: 1;
        color: $text-muted;
        pointer: pointer;
    }
    SessionTabClose:hover, SessionTabClose:focus {
        color: $error;
        text-style: bold reverse;
    }
    """

    def __init__(self, mode_name: str) -> None:
        super().__init__("×", id=f"close-{mode_name}")
        self.mode_name = mode_name
        self.tooltip = "Close tab (or middle-click its label)"

    def action_close_tab(self) -> None:
        self.app.post_message(messages.SessionArchive(self.mode_name))

    def on_click(self, event: events.Click) -> None:
        if event.button in {1, 2}:
            event.stop()
            self.action_close_tab()


class Underline(Widget):
    """The animated underline beneath tabs."""

    COMPONENT_CLASSES = {"underline--bar"}
    """
    | Class | Description |
    | :- | :- |
    | `underline--bar` | Style of the bar (may be used to change the color). |
    """

    highlight_start = reactive(0)
    """First cell in highlight."""
    highlight_end = reactive(0)
    """Last cell (inclusive) in highlight."""
    show_highlight: reactive[bool] = reactive(True)
    """Flag to indicate if a highlight should be shown at all."""

    class Clicked(Message):
        """Inform ancestors the underline was clicked."""

        offset: Offset
        """The offset of the click, relative to the origin of the bar."""

        def __init__(self, offset: Offset) -> None:
            self.offset = offset
            super().__init__()

    @property
    def _highlight_range(self) -> tuple[int, int]:
        """Highlighted range for underline bar."""
        return (
            (self.highlight_start, self.highlight_end)
            if self.show_highlight
            else (0, 0)
        )

    def render(self) -> RenderResult:
        """Render the bar."""
        bar_style = self.get_component_rich_style("underline--bar")
        return Bar(
            highlight_range=self._highlight_range,
            highlight_style=RichStyle.from_color(bar_style.color),
            background_style=RichStyle.from_color(bar_style.bgcolor),
        )

    def _on_click(self, event: events.Click):
        """Catch clicks, so that the underline can activate the tabs."""
        event.stop()
        self.post_message(self.Clicked(event.screen_offset))


class SessionsTabs(Widget):

    ALLOW_SELECT = False
    app: getters.app[ToadApp] = getters.app(ToadApp)

    title_container = getters.query_one("#title-container", Widget)

    current_session = reactive("", init=False)
    _last_tabs: tuple[OpenTab, ...] | None = None

    def on_mount(self) -> None:
        self.current_session = self.app.current_mode
        self.app.mode_change_signal.subscribe(self, self.handle_mode_change)
        self.app.session_update_signal.subscribe(
            self, self.handle_session_update_signal
        )
        self.app.open_tabs_changed.subscribe(self, self._tabs_changed)
        self.update_underline(self.current_session, animate=False)
        self.call_after_refresh(self.update_underline, self.current_session)

    def handle_mode_change(self, mode: str) -> None:
        if self.screen.is_active:
            self.call_later(self._sync_tabs)

    def watch_current_session(self, old_session: str, new_session: str) -> None:
        self.query(".-current").remove_class("-current")
        self.query(f"#{new_session}").add_class("-current")
        if old_session:
            self.update_underline(old_session, animate=False)

        self.update_underline(new_session, animate=False)

    def update_underline(self, session: str | None = None, animate: bool = True):
        if not self.is_mounted or not self.is_attached:
            return
        if session is None:
            session = self.current_session
        if not session:
            return
        if current_label := self.query_one_optional(f"#{session}", SessionLabel):
            tab_region = current_label.virtual_region.shrink((0, 1, 0, 1))
            if not tab_region:
                return
            start, end = tab_region.column_span
            underline = self.query_one(Underline)
            if animate:
                underline.animate("highlight_start", start, duration=0.3)
                underline.animate(
                    "highlight_end",
                    end,
                    duration=0.3,
                    on_complete=partial(self.scroll_to_center, current_label),
                )
            else:
                underline.highlight_start = start
                underline.highlight_end = end
                self.scroll_to_center(current_label, animate=False)

    def render_session_label(self, session: OpenTab) -> Content:
        if session.unread:
            return Content.assemble(session.title, (f" ({session.unread})", "bold $accent"))
        return Content(session.title)

    def compose(self) -> ComposeResult:
        with containers.HorizontalGroup(id="title-container"):
            for session in self.app.open_tabs:
                yield SessionLabel(
                    self.render_session_label(session),
                    id=session.mode_name,
                    classes="-current" if session.mode_name == self.screen.id else "",
                )
                yield SessionTabClose(session.mode_name)
        yield Underline()

    async def handle_session_update_signal(
        self, update: tuple[str, SessionDetails | None]
    ) -> None:
        if self.screen.is_active:
            await self._sync_tabs()

    async def _tabs_changed(self, _update: None) -> None:
        if self.screen.is_active:
            await self._sync_tabs()

    async def _sync_tabs(self) -> None:
        if not self.is_attached or not self.screen.is_active:
            return
        tabs = self.app.open_tabs
        if tabs == self._last_tabs and self.current_session == self.app.current_mode:
            return
        labels = {label.id: label for label in self.query(SessionLabel)}
        desired = {tab.mode_name for tab in tabs}
        for label in labels.values():
            if label.id not in desired:
                await self.query(f"#{label.id}, #close-{label.id}").remove()
        for tab in tabs:
            content = self.render_session_label(tab)
            if label := labels.get(tab.mode_name):
                if label.render().plain != content.plain:
                    label.update(content)
            else:
                await self.title_container.mount(
                    SessionLabel(content, id=tab.mode_name), SessionTabClose(tab.mode_name)
                )
        order = {identity: index for index, identity in enumerate(
            identity for tab in tabs for identity in (tab.mode_name, f"close-{tab.mode_name}")
        )}
        if [widget.id for widget in self.title_container.children] != list(order):
            self.title_container.sort_children(key=lambda widget: order[widget.id])
        self.current_session = self.app.current_mode
        self._last_tabs = tabs
        self.call_after_refresh(self.update_underline, self.current_session, False)
