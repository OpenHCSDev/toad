from toad.core import events as core_events
from toad.core_event_carrier import CoreEventMessage
from toad.core import session_requests
import asyncio
from collections.abc import Iterable
from typing import ClassVar

from rich.style import Style as RichStyle
from textual import containers, events, getters, widgets
from textual.app import ComposeResult, RenderResult
from textual.binding import BindingType
from textual.content import Content
from textual.geometry import Offset, Region
from textual.message import Message
from textual.renderables.bar import Bar
from textual.strip import Strip
from textual.style import Style
from ui_theme.scheme import AccentColour
from textual.widget import Widget

from toad import messages
from agent_comms.mro_dispatch import handles
from toad.core.events import SessionChangedEvent
from toad.core_event_carrier import CoreEventReceiver
from toad.app import ToadApp
from toad.session_tracker import OpenTab
from toad.textual_colours import Animated
from ui_theme.effects import TAB_WIPE
from toad.widgets.selection import ViewLabel


class SessionLabel(ViewLabel, widgets.Label):
    ALLOW_SELECT = False

    def on_resize(self) -> None:
        # A label laid out for the first time, or at a new width, moves the
        # cells the underline marks.
        self.query_ancestor(SessionsTabs).show_selected_tab()

    def on_click(self, event: events.Click) -> None:
        if self.id is not None:
            if event.button == 2:
                event.stop()
                self.app.session_navigation.events.publish(session_requests.SessionArchive(self.id))
            elif event.button == 1:
                # A second message-pump hop lets the old screen's pending
                # full-layout timer run ahead of the user's tab click. The
                # ordinary app mode-switch boundary already captures sidebar
                # navigation and queues its serialized transition.
                self.app.select_session(self.id)


class SessionTabClose(widgets.Static, can_focus=True):
    """Close a tab without selecting it or deleting its saved thread."""

    ALLOW_SELECT = False
    FOCUS_ON_CLICK = False
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
        self.app.session_navigation.events.publish(session_requests.SessionArchive(self.mode_name))

    def on_click(self, event: events.Click) -> None:
        if event.button in {1, 2}:
            event.stop()
            self.action_close_tab()


class Underline(Animated, Widget):
    """The underline beneath tabs; a wipe crosses the current tab's highlight when it is chosen."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {"underline--bar"}
    """
    | Class | Description |
    | :- | :- |
    | `underline--bar` | Style of the bar (may be used to change the color). |
    """

    class Clicked(Message):
        """Inform ancestors the underline was clicked."""

        offset: Offset
        """The offset of the click, relative to the origin of the bar."""

        def __init__(self, offset: Offset) -> None:
            self.offset = offset
            super().__init__()

    @property
    def _highlight_range(self) -> tuple[int, int]:
        """The selected tab's cells, read from its label when the bar is drawn."""
        return self.query_ancestor(SessionsTabs).selected_span

    def render(self) -> RenderResult:
        """Render the bar."""
        bar_style = self.get_component_rich_style("underline--bar")
        return Bar(
            highlight_range=self._highlight_range,
            highlight_style=RichStyle.from_color(bar_style.color),
            background_style=RichStyle.from_color(bar_style.bgcolor),
        )

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        animation = self.animation
        width = strip.cell_length
        # The highlighted tab can lie partly or wholly beyond the visible strip.
        start, end = (min(cell, width) for cell in self._highlight_range)
        if animation is None or start >= end:
            return strip
        tab = self.app.colours.paint_band(animation.frame(), strip.crop(start, end))
        return Strip.join((strip.crop(0, start), tab, strip.crop(end, width)))

    def _on_click(self, event: events.Click):
        """Catch clicks, so that the underline can activate the tabs."""
        event.stop()
        self.post_message(self.Clicked(event.screen_offset))


class SessionsTabs(CoreEventReceiver, Widget):

    ALLOW_SELECT = False
    app: getters.app[ToadApp] = getters.app(ToadApp)

    title_container = getters.query_one("#title-container", Widget)

    _last_tabs: tuple[OpenTab, ...] | None = None

    def __init__(self) -> None:
        super().__init__()
        self._sync_lock = asyncio.Lock()

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

    def on_mount(self) -> None:
        # Metadata can arrive after compose built the labels. Keep that exact
        # rendered snapshot as the cache, then reconcile the mounted widgets.
        self.observe_core(self.app.events)
        self.subscribe_core(self.app.session_tracker.events)
        self.call_later(self._sync_tabs)
        self.call_after_refresh(self.show_selected_tab)

    @handles(core_events.SessionSelected)
    async def handle_mode_change(self, event: CoreEventMessage) -> None:
        if self.screen.is_active:
            self.call_later(self._sync_tabs)
            self.call_after_refresh(self.show_selected_tab)
            self.query_one(Underline).run_effect(TAB_WIPE)

    def sync_current(self) -> None:
        for label in self.query(SessionLabel):
            label.paint_current(label.id == self.app.selected_mode)

    @property
    def selected_span(self) -> tuple[int, int]:
        """The cells under the selected tab's label; empty until that label is laid out."""
        selected = self.app.selected_mode
        label = self.query_one_optional(f"#{selected}", SessionLabel) if selected else None
        return (0, 0) if label is None else label.virtual_region.shrink((0, 1, 0, 1)).column_span

    def show_selected_tab(self) -> None:
        """Redraw the underline and bring the selected tab into the strip.

        Called when the selection or a label's geometry changes. It reads the
        selection when it runs, so a deferred call cannot restore an earlier tab.
        """
        if not self.is_mounted or not self.is_attached:
            return
        self.query_one(Underline).refresh()
        selected = self.app.selected_mode
        if selected and (label := self.query_one_optional(f"#{selected}", SessionLabel)):
            if label.virtual_region:
                self.scroll_to_center(label, animate=False)

    def render_session_label(self, session: OpenTab) -> Content:
        title = session.label()
        if session.unread.label:
            badge_style = (Style(foreground=self.app.colours.colour(AccentColour))
                           if session.unread.highlighted else Style())
            return Content.assemble(title, (f" {session.unread.label}", badge_style))
        return title

    def compose(self) -> ComposeResult:
        tabs = self.app.open_tabs
        self._last_tabs = tabs
        with containers.HorizontalGroup(id="title-container"):
            for session in tabs:
                yield SessionLabel(
                    self.render_session_label(session),
                    id=session.mode_name,
                )
                yield SessionTabClose(session.mode_name)
        yield Underline()

    @handles(SessionChangedEvent)
    async def handle_session_update(self, event: CoreEventMessage) -> None:
        if self.screen.is_active:
            await self._sync_tabs()

    @handles(core_events.OpenTabsChanged)
    async def _tabs_changed(self, event: CoreEventMessage) -> None:
        if self.screen.is_active:
            await self._sync_tabs()

    async def _sync_tabs(self) -> None:
        # Activation and published metadata can request the same catch-up.
        # Serialize the mounted projection, reading the newest tabs after the
        # previous mount completes instead of duplicating IDs or losing updates.
        async with self._sync_lock:
            await self._reconcile_tabs()

    async def _reconcile_tabs(self) -> None:
        while True:
            if not self.is_attached or not self.screen.is_active:
                return
            tabs = self.app.open_tabs
            if tabs == self._last_tabs:
                self.sync_current()
                return
            previous_tabs = {tab.mode_name: tab for tab in self._last_tabs or ()}
            geometry_changed = self._last_tabs is None
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
                            and previous.unread.highlighted == tab.unread.highlighted
                            and len(previous.unread.label) == len(tab.unread.label)
                        )
                        label.update(content, layout=not same_width_count)
                        geometry_changed |= not same_width_count
                else:
                    new_widgets.extend((SessionLabel(content, id=tab.mode_name), SessionTabClose(tab.mode_name)))
                    geometry_changed = True
            if new_widgets:
                await self.title_container.mount(*new_widgets)
            if not self.is_attached:
                return
            order = {identity: index for index, identity in enumerate(
                identity for tab in tabs for identity in (tab.mode_name, f"close-{tab.mode_name}")
            )}
            if [widget.id for widget in self.title_container.children] != list(order):
                self.title_container.sort_children(key=lambda widget: order[widget.id])
                geometry_changed = True
            self.sync_current()
            self._last_tabs = tabs
            if geometry_changed:
                self.call_after_refresh(self.show_selected_tab)
            # Mount/removal yields to metadata publications. Reconcile their
            # actual newest roster before the activation caller can finish.
            if tabs == self.app.open_tabs:
                return
