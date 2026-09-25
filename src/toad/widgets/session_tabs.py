import asyncio
from collections.abc import Iterable
from functools import partial
from typing import ClassVar

from rich.style import Style as RichStyle
from textual import containers, events, getters, widgets
from textual.app import ComposeResult, RenderResult
from textual.binding import BindingType
from textual.content import Content
from textual.geometry import Offset, Region
from textual.message import Message
from textual.reactive import reactive
from textual.renderables.bar import Bar
from textual.widget import Widget

from toad import messages
from toad.app import ToadApp
from toad.session_tracker import OpenTab, SessionDetails
from toad.sidebar_preparation import PreparedTab, TabRosterWork
from toad.widgets.activity_spinner import FRAMES, animated_label


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
    BINDINGS: ClassVar[list[BindingType]] = [("enter,space", "close_tab", "Close tab")]
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

    COMPONENT_CLASSES: ClassVar[set[str]] = {"underline--bar"}
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

    def __init__(self) -> None:
        super().__init__()
        self._spinner_phase = 0
        self._spinner_timer = None
        self._sync_lock = asyncio.Lock()
        self._tab_projection: dict[str, PreparedTab] = {}

    def _get_scrollable_region(self, region: Region) -> Region:
        # The scrollbar occupies the explicit empty top row, not a bottom row.
        # Keep the container origin: moving this clip origin makes viewport-only
        # composition cull the CSS-offset underline even though full renders pass.
        window = super()._get_scrollable_region(region)
        return window.grow((0, 0, self.scrollbar_size_horizontal, 0))

    def _arrange_scrollbars(self, region: Region) -> Iterable[tuple[Widget, Region]]:
        for scrollbar, scrollbar_region in super()._arrange_scrollbars(region):
            if scrollbar is self.horizontal_scrollbar:
                scrollbar_region = scrollbar_region.translate((0, region.y - scrollbar_region.y))
            yield scrollbar, scrollbar_region

    def _sync_spinner(self, tabs: tuple[OpenTab, ...]) -> None:
        timer = self._spinner_timer
        if timer is None:
            return
        if self.screen.is_active and any(tab.title.startswith(("⌛ ", "● ")) for tab in tabs):
            timer.resume()
        else:
            timer.pause()

    def _animate_busy(self) -> None:
        tabs = self._last_tabs or ()
        if not self.screen.is_active or not any(
            tab.title.startswith(("⌛ ", "● ")) for tab in tabs
        ):
            self._sync_spinner(())
            return
        self._spinner_phase = (self._spinner_phase + 1) % len(FRAMES)
        for tab in tabs:
            if (tab.title.startswith(("⌛ ", "● "))
                    and (label := self.query_one_optional(f"#{tab.mode_name}", SessionLabel))):
                label.update(self.render_session_label(tab), layout=False)

    def on_mount(self) -> None:
        self._spinner_timer = self.set_interval(.18, self._animate_busy, pause=True)
        # Metadata can arrive after compose built the labels. Keep that exact
        # rendered snapshot as the cache, then reconcile the mounted widgets.
        self.current_session = self.app.current_mode
        self.app.mode_change_signal.subscribe(self, self.handle_mode_change)
        self.app.session_update_signal.subscribe(
            self, self.handle_session_update_signal
        )
        self.app.open_tabs_changed.subscribe(self, self._tabs_changed)
        self.call_later(self._sync_tabs)
        self.update_underline(self.current_session, animate=False)
        self.call_after_refresh(self.update_underline, self.current_session)
        self._sync_spinner(self.app.open_tabs)

    def handle_mode_change(self, mode: str) -> None:
        if self.screen.is_active:
            self.call_later(self._sync_tabs)

    def watch_current_session(self, old_session: str, new_session: str) -> None:
        self.query(".-current").remove_class("-current")
        self.query(f"#{new_session}").add_class("-current")
        if self.app._atomic_mode_switch:
            self.call_after_refresh(self.update_underline, new_session, False)
            return
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
        prepared = self._tab_projection.get(session.mode_name)
        if prepared is not None and prepared.source == session:
            return prepared.content(self._spinner_phase)
        title = animated_label(
            session.title,
            busy=session.title.startswith(("⌛ ", "● ")),
            phase=self._spinner_phase,
        )
        if session.unread:
            return Content.assemble(title, (f" ({session.unread})", "bold $accent"))
        return Content(title)

    def compose(self) -> ComposeResult:
        tabs = self.app.open_tabs
        self._last_tabs = tabs
        with containers.HorizontalGroup(id="title-container"):
            for session in tabs:
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
        # Activation and published metadata can request the same catch-up.
        # Serialize the mounted projection, reading the newest tabs after the
        # previous mount completes instead of duplicating IDs or losing updates.
        async with self._sync_lock:
            await self._reconcile_tabs()

    async def _reconcile_tabs(self) -> None:
        if not self.is_attached or not self.screen.is_active:
            return
        while True:
            tabs = self.app.open_tabs
            if tabs == self._last_tabs and self.current_session == self.app.current_mode:
                self._sync_spinner(tabs)
                return
            prepared = await self.app.preparation.submit(TabRosterWork(tabs))
            if not self.is_attached or not self.screen.is_active:
                return
            if tabs == self.app.open_tabs:
                break
            # The caller may be the activation transaction. Finish its newest
            # roster here rather than return "ready" with stale geometry and
            # defer the real work to an unrelated callback.
        self._tab_projection = {tab.source.mode_name: tab for tab in prepared}
        previous_tabs = {tab.mode_name: tab for tab in self._last_tabs or ()}
        geometry_changed = self._last_tabs is None
        mode_changed = self.current_session != self.app.current_mode
        labels = {label.id: label for label in self.query(SessionLabel)}
        desired = {tab.mode_name for tab in tabs}
        obsolete = set(labels) - desired
        if obsolete:
            retired_ids = obsolete | {f"close-{identity}" for identity in obsolete}
            await self.title_container.remove_children(
                child for child in self.title_container.children if child.id in retired_ids
            )
            geometry_changed = True
        new_widgets: list[Widget] = []
        for tab in tabs:
            content = self.render_session_label(tab)
            if label := labels.get(tab.mode_name):
                if label.render().plain != content.plain:
                    previous = previous_tabs.get(tab.mode_name)
                    same_width_count = (
                        previous is not None and previous.title == tab.title
                        and bool(previous.unread) == bool(tab.unread)
                        and len(str(previous.unread)) == len(str(tab.unread))
                    )
                    label.update(content, layout=not same_width_count)
                    geometry_changed |= not same_width_count
            else:
                new_widgets.extend((SessionLabel(content, id=tab.mode_name), SessionTabClose(tab.mode_name)))
                geometry_changed = True
        if new_widgets:
            await self.title_container.mount(*new_widgets)
        order = {identity: index for index, identity in enumerate(
            identity for tab in tabs for identity in (tab.mode_name, f"close-{tab.mode_name}")
        )}
        if [widget.id for widget in self.title_container.children] != list(order):
            self.title_container.sort_children(key=lambda widget: order[widget.id])
            geometry_changed = True
        self.current_session = self.app.current_mode
        self._last_tabs = tabs
        self._sync_spinner(tabs)
        if geometry_changed or mode_changed:
            self.call_after_refresh(self.update_underline, self.current_session, False)
