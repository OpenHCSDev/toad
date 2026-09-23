"""Shared activation policy for already-mounted conversation views."""

from dataclasses import dataclass, replace
from functools import cached_property
from typing import TYPE_CHECKING
import asyncio

from textual.events import ScreenResume
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget

if TYPE_CHECKING:
    from toad.widgets.history_anchor import HistoryWindow


@dataclass(frozen=True)
class ViewStyleRevision:
    theme: str
    app_classes: frozenset[str]
    screen_classes: frozenset[str]
    viewport: Size
    source_signature: int
    css_generation: int


class SessionView(Screen):
    _resume_style: ViewStyleRevision | None = None
    _navigation_applied = False
    _navigation_changed = False
    _resume_styles_changed = False

    def _on_timer_update(self) -> None:
        if (self.is_current and self.app._pending_mode_switch is not None
                and self.app._pending_mode_switch != self.id):
            # The pending layout is still needed if this busy screen is
            # reopened. Keep its invalidation flags but do not measure the
            # screen the user is leaving before the selected tab can paint.
            self._update_timer.pause()
            return
        super()._on_timer_update()

    @cached_property
    def history_anchors(self) -> set["HistoryWindow"]:
        """Only windows with an active render transaction need compensation."""
        return set()

    def _refresh_layout(self, size: Size | None = None, scroll: bool = False) -> None:
        from toad.widgets.history_anchor import HistoryAnchor

        # Keep the last committed geometry: reading virtual_region here can
        # itself rebuild Textual's invalidated map with the new child positions.
        # Only the reader's current scroll/follow intent is refreshed pre-layout.
        anchors = [
            (window, replace(window.history_anchor, scroll_y=window.scroll_y,
                             follow_tail=window.follows_tail, scroll_revision=window.scroll_revision))
            for window in self.history_anchors
            if window.history_anchor is not None and window.history_anchor.widget.is_attached
        ]
        if not anchors:
            super()._refresh_layout(size, scroll)
            return
        # Screen normally paints from inside _refresh_layout. Do not expose the
        # prepend/eviction coordinates before compensating for their height.
        with self.app.batch_update():
            super()._refresh_layout(size, scroll)
            changed = False
            for window, position in anchors:
                previous = window.scroll_y
                position.restore(window)
                window.history_anchor = HistoryAnchor.capture(position.widget, window)
                changed |= window.scroll_y != previous
            if changed:
                super()._refresh_layout(size, scroll=True)
            for window, _position in anchors:
                if window.history_layout_ready is not None:
                    window.history_layout_ready.set()

    def _screen_resized(self, size: Size) -> None:
        if (self.stack_updates and self.is_attached
                and self._navigation_applied and not self._resume_styles_changed
                and self._size == size and not self._layout_required
                and not self._layout_widgets):
            # A resumed mounted tab has already been measured at this width.
            # Textual's full reflow walks all descendants even when only the
            # viewport/visibility needs reconciliation. Keep the full path
            # whenever styles, geometry, or hidden content were invalidated.
            self._refresh_layout(size, scroll=True)
        else:
            super()._screen_resized(size)
            if (self.stack_updates and self.is_attached and self._size == size
                    and not self._layout_widgets):
                # Mode activation just performed and painted a full reflow.
                # Textual leaves the earlier _layout_required bit set for its
                # later timer, so layout_navigation otherwise reflows the
                # same unchanged tree again before accepting input. A fresh
                # widget invalidation repopulates _layout_widgets; preserve
                # scroll work separately if the reflow requested it.
                self._layout_required = False

    def get_widget_and_offset_at(self, x: int, y: int):
        widget, offset = super().get_widget_and_offset_at(x, y)
        # Diff auto-layout and history virtualization can retire a widget before
        # the compositor commits its next map. A stale hit is not a valid new
        # selection endpoint (Textual otherwise asserts that it has a parent).
        if widget is not None and (
            not widget.is_attached or (offset is not None and not isinstance(widget.parent, Widget))
        ):
            return None, None
        return widget, offset

    def _update_focus_styles(
        self, focused: Widget | None = None, blurred: Widget | None = None
    ) -> None:
        """Only changed focus-within ancestors can invalidate their descendants."""
        entered = set(focused.ancestors_with_self) if focused is not None else set()
        exited = set(blurred.ancestors_with_self) if blurred is not None else set()
        changed = {node for node in entered ^ exited if node._has_focus_within}
        roots = [node for node in changed if not any(parent in changed for parent in node.ancestors)]
        if roots:
            self.app.stylesheet.update_nodes(
                {child for root in roots for child in root.walk_children(with_self=True)},
                animate=True,
            )

    def capture_navigation(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar

        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.capture_navigation()

    async def prepare_navigation(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        self._navigation_changed = False
        if side_bar := self.query_one_optional(SideBar):
            panels = tuple(side_bar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            side_bar.restore_navigation()
            self._navigation_changed |= before != tuple(panel.collapsed for panel in panels)
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.prepare_navigation()
            await sidebar.present_cached_sessions()
            # The snapshot can differ only in activity, unread, or labels.
            # Such rows repaint in place. Mount, reorder, expansion and size
            # changes independently invalidate Textual's layout, so a new wire
            # revision by itself does not justify reflowing the transcript.

    async def layout_navigation(self) -> None:
        """Measure the complete tree, then position its viewport before painting."""
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.side_bar import SideBar

        sidebar = self.query_one_optional(CommsSidebar)
        if (self._navigation_applied and not self._navigation_changed
                and self._size == self.app.size and not self._layout_required
                and not self._scroll_required and not self._layout_widgets):
            # Textual's ScreenResume already reflowed this mounted screen.
            # Repeating its full compositor pass on every tab activation is
            # unnecessary when navigation/geometry did not change.
            if sidebar is not None:
                if sidebar.restore_scroll():
                    self._refresh_layout(self.app.size, scroll=True)
                sidebar.navigation_ready.set()
            return
        sizes = {
            widget: widget.size
            for widget in sidebar.query_ancestor(SideBar).walk_children(Widget)
        } if sidebar is not None else {}
        self._refresh_layout(self.app.size)
        if sidebar is not None:
            if sidebar.restore_scroll():
                self._refresh_layout(self.app.size, scroll=True)
            # Reflow exposes rows and queues their Resize/Show handlers. Let
            # those handlers invalidate measurements before committing a frame.
            resized = [widget for widget, size in sizes.items() if widget.size != size]
            if resized:
                await asyncio.gather(*(self._settle_widget(widget) for widget in resized))
                self._refresh_layout(self.app.size)
            sidebar.navigation_ready.set()
        self._layout_required = False
        self._scroll_required = False
        self._dirty_widgets.clear()
        self._navigation_applied = True

    @staticmethod
    async def _settle_widget(widget: Widget) -> None:
        """Await queued resize handlers, or the widget's removal, without polling."""
        processed = asyncio.Event()
        if widget._task is None or not widget.call_later(processed.set):
            return
        completed = asyncio.create_task(processed.wait())
        try:
            await asyncio.wait((completed, widget._task), return_when=asyncio.FIRST_COMPLETED)
        finally:
            completed.cancel()
            await asyncio.gather(completed, return_exceptions=True)

    def _on_screen_resume(self, event: ScreenResume) -> None:
        # rules_map is a disposable cache. Re-parsing identical stylesheet
        # sources replaces that dictionary and used to force a full-tree
        # restyle of every aged tab when it was next selected. Detect actual
        # CSS source/theme changes instead; source content and scope are both
        # included, while App's generation covers theme-variable refreshes.
        sources = self.app.stylesheet.source
        signature = hash(tuple(
            (location, source.content, source.is_defaults, source.tie_breaker, source.scope)
            for location, source in sources.items()
        ))
        revision = ViewStyleRevision(
            self.app.theme, self.app.classes, self.classes, self.app.size,
            signature, self.app._css_update_count,
        )
        # Framework dispatch continues to Screen's handler after this adapter.
        # Layout/paint still run; unchanged trees do not need another CSS walk.
        # Newly mounted nodes already received the current stylesheet. A second
        # full-tree CSS walk on their first activation just delays the spinner.
        event.refresh_styles = (event.refresh_styles and self._resume_style is not None
                                and revision != self._resume_style)
        self._resume_styles_changed = event.refresh_styles
        self._resume_style = revision
