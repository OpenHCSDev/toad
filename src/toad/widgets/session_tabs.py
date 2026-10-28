import asyncio
from collections.abc import Iterable

from metaclass_registry.mro_dispatch import handles
from rich.style import Style as RichStyle
from textual import containers, events, getters, widgets
from textual._activation import PrimaryActivation
from textual.app import ComposeResult, RenderResult
from toad.widget_actions import ActivationKeys
from textual.color import TRANSPARENT
from textual.content import Content
from textual.css.scalar import Scalar, ScalarOffset, Unit
from textual.geometry import Offset, Region, Spacing
from textual.layouts.vertical import VerticalLayout
from textual.message import Message
from textual.renderables.bar import Bar
from textual.style import Style
from textual.widget import Widget
from ui_theme.effects import NEW_TEXT, Amount, Transition
from ui_theme.scheme import (
    AccentColour,
    ErrorColour,
    ForegroundColour,
    HeaderToneColour,
    MutedColour,
)

from toad.core import events as core_events
from toad.core import session_requests
from toad.core.events import SessionChangedEvent
from toad.core_event_carrier import CoreEventReceiver
from toad.frame_presentation import Animated
from toad.session_tracker import OpenTab
from toad.app_node import ToadNode
from toad.widget_view import AUTO, FILL, WidgetView
from toad.widgets.selection import ChangingText, ViewLabel


class SessionLabel(WidgetView, PrimaryActivation, ViewLabel, ChangingText, widgets.Label):
    ALLOW_SELECT = False
    width = AUTO
    height = Scalar.from_number(1)
    padding = Spacing(0, 1, 0, 1)

    @property
    def current(self) -> bool:
        return self.id == self.app.selected_mode

    @property
    def paint_text_style(self):
        return RichStyle(dim=not self.mouse_hover)

    @property
    def background_tint(self):
        return (self.app.colours.colour(ForegroundColour).multiply_alpha(0.1)
                if self.mouse_hover else TRANSPARENT)

    def __init__(self, tab: OpenTab, **kwargs):
        super().__init__(Content(), **kwargs)
        self.present(tab)

    def present(self, tab: OpenTab) -> bool:
        """The label owns activity, unread ink and native text width."""
        content = self.activity_content(tab.title, tab.label(), tab.busy, prefix=Content())
        if tab.unread.label:
            badge = (Style(foreground=self.app.colours.colour(AccentColour))
                     if tab.unread.highlighted else Style())
            content = Content.assemble(content, (f" {tab.unread.label}", badge))
        width_changed = content.cell_length != self.content.cell_length
        self.update(content, layout=width_changed)
        return width_changed

    def on_resize(self) -> None:
        # A label laid out for the first time, or at a new width, moves the
        # cells the underline marks.
        self.query_ancestor(SessionsTabs).show_selected_tab()

    @property
    def primary_activation(self):
        return self.action_select_session

    def action_select_session(self) -> None:
        if self.id is not None:
            self.app.select_session(self.id)

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
                self.action_select_session()


class SessionTabClose(WidgetView, ActivationKeys, widgets.Static, can_focus=True):
    """Close a tab without selecting it or deleting its saved thread."""

    ALLOW_SELECT = False
    FOCUS_ON_CLICK = False
    activation_buttons = (1, 2)
    width = Scalar.from_number(2)
    height = Scalar.from_number(1)

    @property
    def paint_foreground(self):
        return self.app.colours.colour(ErrorColour if self.mouse_hover or self.has_focus else MutedColour)

    @property
    def text_style(self):
        return RichStyle(bold=self.mouse_hover or self.has_focus, reverse=self.mouse_hover or self.has_focus)

    def __init__(self, mode_name: str) -> None:
        super().__init__("×", id=f"close-{mode_name}")
        self.mode_name = mode_name
        self.tooltip = "Close tab (or middle-click its label)"

    @property
    def primary_activation(self):
        return self.close_tab

    def close_tab(self) -> None:
        self.app.session_navigation.events.publish(session_requests.SessionArchive(self.mode_name))

# The selected tab's underline travels from the cells it marked to the new ones.
TAB_SLIDE = Transition(Amount, 0.0, 1.0, duration=0.18, frames_per_second=60)


class Underline(WidgetView, Animated[Amount]):
    """The track under the tab cells, marking the selected tab's cells.

    It is laid out under the cells themselves (TabCells), so it spans every
    cell however far the strip scrolls. When the marked cells move (another tab
    chosen, tabs reordered, closed, opened or renamed) it slides from what it
    drew to them, on the app clock; it repaints one row per frame.
    """

    width = FILL
    height = Scalar.from_number(1)
    # The cells it drew last: where the next slide starts.
    _drawn: tuple[float, float] = (0.0, 0.0)
    _origin: tuple[float, float] = (0.0, 0.0)

    def mark_selected(self) -> None:
        """The selected cells may have moved; slide to them from what is drawn."""
        start, end = self._drawn
        if start < end and self._drawn != self.selected_cells:
            self._origin = self._drawn
            self.run_effect(TAB_SLIDE)
        self.refresh()

    class Clicked(Message):
        """Inform ancestors the underline was clicked."""

        offset: Offset
        """The offset of the click, relative to the origin of the bar."""

        def __init__(self, offset: Offset) -> None:
            self.offset = offset
            super().__init__()

    @property
    def selected_cells(self) -> tuple[float, float]:
        """The selected tab's cells, read from its label when the bar is drawn."""
        start, end = self.query_ancestor(SessionsTabs).selected_span
        return float(start), float(end)

    def render(self) -> RenderResult:
        """Render the bar."""
        colours = self.app.colours
        background = colours.colour(HeaderToneColour) + colours.colour(ForegroundColour).multiply_alpha(0.1)
        amount = self.effect_frame(TAB_SLIDE).value
        (from_start, from_end), (to_start, to_end) = self._origin, self.selected_cells
        self._drawn = (from_start + (to_start - from_start) * amount,
                       from_end + (to_end - from_end) * amount)
        return Bar(
            highlight_range=self._drawn,
            highlight_style=RichStyle.from_color(colours.colour(AccentColour).rich_color),
            background_style=RichStyle.from_color(background.rich_color),
        )

    def _on_click(self, event: events.Click):
        """Catch clicks, so that the underline can activate the tabs."""
        event.stop()
        self.post_message(self.Clicked(event.screen_offset))


class SessionTitles(WidgetView, containers.HorizontalGroup):
    """The tab cells: each tab's label and close button."""

    width = AUTO
    height = Scalar.from_number(1)


class TabCells(WidgetView, containers.VerticalGroup):
    """The tab cells over their underline, as wide as the cells or the strip, whichever is wider.

    The underline's columns are the cells' columns by layout, so the selected
    tab's span needs no translation and is never past the underline's end.
    """

    # WidgetView declares its geometry inputs as None, so mypy reads every
    # Scalar override as a new type (the other views here hit the same error).
    width = AUTO  # type: ignore[assignment]
    min_width = Scalar(100, Unit.PERCENT, Unit.WIDTH)  # type: ignore[assignment]
    height = Scalar.from_number(2)
    placement_offset = ScalarOffset.from_offset((0, 1))


class SessionsTabs(WidgetView, CoreEventReceiver, Widget, ToadNode):
    DEFAULT_LAYOUT = VerticalLayout
    width = FILL
    height = Scalar.from_number(3)
    box_sizing = "content-box"
    overflow_x = "auto"
    vertical_scrollbar_size = 0

    ALLOW_SELECT = False

    title_container = getters.query_one("#title-container", Widget)

    _last_tabs: dict[str, OpenTab] | None = None

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

    @property
    def display(self) -> bool:
        return self.app.show_sessions

    def _visibility_changed(self, shown: bool) -> None:
        self.refresh(layout=True)

    def on_mount(self) -> None:
        self.watch(self.app, "show_sessions", self._visibility_changed)
        # Metadata can arrive after compose built the labels. Keep that exact
        # rendered snapshot as the cache, then reconcile the mounted widgets.
        self.observe_core(self.app.events)
        self.observe_core(self.app.coordination_access.events)
        self.subscribe_core(self.app.session_tracker.events)
        self.call_later(self._sync_tabs)
        self.call_after_refresh(self.show_selected_tab)

    @handles(core_events.SessionSelected)
    async def handle_mode_change(self, event: core_events.SessionSelected) -> None:
        if self.screen.is_active:
            for mode in (event.previous_mode, event.mode_name):
                if mode and (label := self.query_one_optional(f"#{mode}", SessionLabel)) is not None:
                    label.paint_current()
            self.call_later(self._sync_tabs)
            self.call_after_refresh(self.show_selected_tab)

    @property
    def selected_span(self) -> tuple[int, int]:
        """The selected tab's cells, label and close button; empty until they are laid out."""
        selected = self.app.selected_mode
        if not selected:
            return 0, 0
        cells = [cell.virtual_region for cell in self.title_container.query_children(f"#{selected}, #close-{selected}")]
        return Region.from_union(cells).column_span if cells else (0, 0)

    def show_selected_tab(self) -> None:
        """Redraw the underline and bring the selected tab into the strip.

        Called when the selection or a label's geometry changes. It reads the
        selection when it runs, so a deferred call cannot restore an earlier tab.
        """
        if not self.is_mounted or not self.is_attached:
            return
        self.query_one(Underline).mark_selected()
        selected = self.app.selected_mode
        if selected and (label := self.query_one_optional(f"#{selected}", SessionLabel)):
            if label.virtual_region:
                self.scroll_to_center(label, animate=False)

    def compose(self) -> ComposeResult:
        tabs = self.app.open_tabs
        self._last_tabs = {tab.mode_name: tab for tab in tabs}
        with TabCells():
            with SessionTitles(id="title-container"):
                for session in tabs:
                    yield SessionLabel(session, id=session.mode_name)
                    yield SessionTabClose(session.mode_name)
            yield Underline()

    @handles(SessionChangedEvent)
    async def handle_session_update(self, event: SessionChangedEvent) -> None:
        if self.screen.is_active:
            await self._sync_tabs()

    @handles(core_events.NamedThreadRowsChanged)
    async def _row_state_changed(self, event: core_events.NamedThreadRowsChanged) -> None:
        if not self.screen.is_active:
            return
        async with self._sync_lock:
            if self._last_tabs is None:
                return
            sessions = self.app.session_navigation
            observation = self.app.coordination_access.observation
            geometry_changed = False
            members = {entry.mode: entry for entry in sessions.members}
            for mode in self._last_tabs.keys() & members.keys():
                previous = self._last_tabs[mode]
                if previous.affected_by(event.names):
                    if (label := self.query_one_optional(f"#{mode}", SessionLabel)) is not None:
                        tab = observation.tab(members[mode], sessions)
                        geometry_changed |= label.present(tab)
                        self._last_tabs[mode] = tab
            if geometry_changed:
                self.call_after_refresh(self.show_selected_tab)

    @handles(core_events.SidebarPresented)
    async def _sidebar_presented(self, event: core_events.SidebarPresented) -> None:
        async with self._sync_lock:
            geometry_changed = False
            for mode, tab in (self._last_tabs or {}).items():
                if (label := self.query_one_optional(f"#{mode}", SessionLabel)) is not None:
                    geometry_changed |= label.present(tab)
            if geometry_changed:
                self.call_after_refresh(self.show_selected_tab)

    @handles(core_events.OpenTabsChanged, core_events.LinkContextChanged)
    async def _tabs_changed(self, event: core_events.OpenTabsChanged | core_events.LinkContextChanged) -> None:
        """A thread tab is a thread row: it repaints when an open session's state changes too."""
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
            if self._last_tabs is not None and tabs == tuple(self._last_tabs.values()):
                return
            previous_tabs = self._last_tabs or {}
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
                if label := labels.get(tab.mode_name):
                    if previous_tabs.get(tab.mode_name) != tab:
                        geometry_changed |= label.present(tab)
                else:
                    new_widgets.extend((SessionLabel(tab, id=tab.mode_name), SessionTabClose(tab.mode_name)))
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
            # A tab that opened or moved among the others rises into its new cells.
            before = list(previous_tabs)
            for index, tab in enumerate(tabs):
                if before[index:index + 1] != [tab.mode_name] and (
                        label := self.query_one_optional(f"#{tab.mode_name}", SessionLabel)):
                    label.run_effect(NEW_TEXT)
            self._last_tabs = {tab.mode_name: tab for tab in tabs}
            if geometry_changed:
                self.call_after_refresh(self.show_selected_tab)
            # Mount/removal yields to metadata publications. Reconcile their
            # actual newest roster before the activation caller can finish.
            if tabs == self.app.open_tabs:
                return
