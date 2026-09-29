"""Shared activation policy for already-mounted conversation views."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import cached_property
from typing import TYPE_CHECKING, cast

from textual.css.model import RuleSet, SelectorType
from textual.css.stylesheet import CssSource
from textual.dom import DOMNode
from textual.events import Resize, ScreenResume
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget

from toad.widgets.side_bar import SidebarFocusOwner

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class ViewStyleRevision:
    theme: str
    app_classes: frozenset[str]
    screen_classes: frozenset[str]
    viewport: Size
    sources: tuple[tuple[tuple[str, str], CssSource], ...]
    css_generation: int


class SessionView(SidebarFocusOwner, Screen):
    # Keep measured geometry for fast revisits, but do not retain every inactive
    # tab's rendered line/segment graph in the cyclic collector's live heap.
    RETAIN_INACTIVE_PAINT = False

    _resume_style: ViewStyleRevision | None = None
    _navigation_applied = False
    _navigation_changed = False
    _resume_styles_changed = False
    _first_frame_presented = False
    _first_frame_flush_queued = False
    _presentation_revision = 0
    _navigation_frame_pending = False

    @property
    def coordination_root(self) -> str | None:
        return None

    @cached_property
    def viewport_presentation(self):
        from toad.widgets.viewport_body import ViewportPresentation
        return ViewportPresentation(self)

    def on_screen_suspend(self) -> None:
        self._presented_event.set()
        self.viewport_presentation.suspend()

    def on_screen_resume(self) -> None:
        self.viewport_presentation.request()

    @cached_property
    def _presented_event(self) -> asyncio.Event:
        return asyncio.Event()

    async def wait_presented(self) -> bool:
        await self._presented_event.wait()
        return self.is_attached and self.is_current and not self._navigation_frame_pending

    @cached_property
    def _initial_frame_callbacks(self) -> dict[tuple[Widget, Callable[[], object]], None]:
        return {}

    def call_after_first_frame(self, owner: Widget, callback: Callable[[], object]) -> None:
        """Defer initial source work until this view's first presented frame.

        A normal after-refresh callback can run inside a paint-suppressed
        navigation batch. The owning widget still receives and executes the
        callback through its ordinary message pump once presentation completes.
        """
        if (self._first_frame_presented and not self._navigation_frame_pending
                and not cast("ToadApp", self.app)._atomic_mode_switch):
            owner.call_after_refresh(callback)
        elif not self._closing and not self._closed:
            self._initial_frame_callbacks[owner, callback] = None

    def _finish_first_frame(self) -> None:
        self._first_frame_flush_queued = False
        if self._closing or self._closed or not self.is_attached or not self.is_current:
            return
        self._first_frame_presented = True
        self._navigation_frame_pending = False
        self._presented_event.set()
        callbacks = tuple(self._initial_frame_callbacks)
        self._initial_frame_callbacks.clear()
        for owner, callback in callbacks:
            if owner.is_attached and not owner._closing and not owner._closed:
                owner.call_later(callback)

    def _frame_presented(self, revision: int) -> None:
        """A writer receipt belongs to the activation that submitted its frame."""
        if revision == self._presentation_revision:
            self._finish_first_frame()

    async def _message_loop_exit(self) -> None:
        self._presented_event.set()
        self._initial_frame_callbacks.clear()
        await super()._message_loop_exit()

    def sidebar_focus_target(self) -> Widget | None:
        # Provisional/loading screens have no input yet.
        return None

    def on_resize(self, _event: Resize) -> None:
        from toad.widgets.side_bar import SideBar

        for sidebar in self.query(SideBar):
            sidebar._apply_layout()
        self.align_tabs_to_sidebars()

    def align_tabs_to_sidebars(self) -> None:
        """The navigation row spans the screen, independent of sidebar placement."""
        from textual.containers import Horizontal

        header = self.query_one_optional("#tab-navigation-header", Horizontal)
        if header is None:
            return
        if header.styles.padding.left:
            header.styles.padding = 0

    def _style_revision(self) -> ViewStyleRevision:
        return ViewStyleRevision(
            self.app.theme, self.app.classes, self.classes, self.app.size,
            tuple(self.app.stylesheet.source.items()), self.app._css_update_count,
        )

    def update_node_styles(self, animate: bool = True) -> None:
        super().update_node_styles(animate=animate)
        if self.is_attached:
            # Breakpoint/root-class updates already styled this complete tree.
            # Record that completed update instead of repeating it next resume.
            self._resume_style = self._style_revision()

    def _on_timer_update(self) -> None:
        app = cast("ToadApp", self.app)
        if app._atomic_mode_switch or (self.is_current and app._pending_mode_switch is not None
                and app._pending_mode_switch != self.id):
            # Keep invalidation flags while the selected tree is reconciled,
            # and on busy screens the reader is leaving. layout_navigation owns
            # the transaction's geometry; ordinary timers resume afterward.
            self._update_timer.pause()
            return
        super()._on_timer_update()

    def _compositor_refresh(self) -> None:
        app = cast("ToadApp", self.app)
        if app._atomic_mode_switch and app._batch_count:
            # _refresh_layout queues this callback, which may run while the
            # navigation transaction awaits mounted/resize handlers. Textual
            # would render the whole intermediate frame only for App._display
            # to discard it at the batch boundary. Keep the dirty regions and
            # repaint intent; the switch's finally block wakes the selected
            # screen after ending the transaction, including error paths.
            self._repaint_required = True
            return
        if not self.viewport_presentation.prepare(self._navigation_frame_pending and self._first_frame_presented):
            return
        super()._compositor_refresh()

    def present_navigation(self) -> None:
        """Commit prepared geometry once, without remeasuring or repainting twice."""
        if self.app._batch_count:
            self.refresh()
            return
        self._set_dirty()
        self._dirty_widgets.add(self)
        self._repaint_required = False
        self._compositor.update_widgets(self._dirty_widgets)
        self._compositor_refresh()

    def _use_viewport_layout(self) -> bool:
        return self.is_current

    def _layout_geometry_targets(self) -> tuple[Widget, ...]:
        return tuple(target for window in self.viewport_presentation.anchors
                     if window.history_anchor is not None
                     for target in window.history_anchor.geometry_targets)

    def _refresh_layout(self, size: Size | None = None, scroll: bool = False) -> None:
        from toad.widgets.history_anchor import HistoryAnchor

        # Keep the last committed geometry: reading virtual_region here can
        # itself rebuild Textual's invalidated map with the new child positions.
        # Only the reader's current scroll/follow intent is refreshed pre-layout.
        tracked = tuple(self.viewport_presentation.anchors)
        anchors = [
            (window, window.history_anchor.before_layout(window))
            for window in tracked
            if window.history_anchor is not None and window.history_anchor.widget.is_attached
        ]
        if not anchors:
            super()._refresh_layout(size, scroll)
            for window in tracked:
                if window.history_layout_ready is not None:
                    window.history_layout_ready.set()
            return
        # Screen normally paints from inside _refresh_layout. Do not expose the
        # prepend/eviction coordinates before compensating for their height.
        with self.app.batch_update():
            for window, position in anchors:
                window.history_anchor = position
            super()._refresh_layout(size, scroll)
            changed = False
            for window, position in anchors:
                previous = window.scroll_y
                position.restore(window)
                window.history_anchor = HistoryAnchor.capture(position.widget, window)
                changed |= window.scroll_y != previous
            if changed:
                super()._refresh_layout(size, scroll=True)
            for window in tracked:
                if window.history_layout_ready is not None:
                    window.history_layout_ready.set()

    def _screen_resized(self, size: Size) -> None:
        if cast("ToadApp", self.app)._atomic_mode_switch and self.is_mounted:
            # App.switch_mode asks for geometry before the destination's tabs
            # and cached sidebar rows have caught up. The navigation transaction
            # measures their completed tree; retain real resize invalidation.
            self._layout_required |= self._size != size
            return
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

    def capture_navigation(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar

        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.capture_navigation()

    def channels_context(self) -> tuple[str, str]:
        """Identity fields supplied to the shared navigation presentation."""
        return "", ""

    async def prepare_presentation(self) -> None:
        """Restore a selected session's retired rich surface, if it has one."""

    async def retire_presentation(self) -> None:
        """Release inactive rich UI without releasing its source or reader intent."""

    async def prepare_navigation(self) -> None:
        from toad.widgets.comms_sidebar import CommsSidebar
        from toad.widgets.session_tabs import SessionsTabs
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        self._presentation_revision += 1
        self._navigation_frame_pending = True
        self._presented_event.clear()
        self._first_frame_flush_queued = False
        self._navigation_changed = False
        for side_bar in self.query(SideBar):
            panels = tuple(side_bar.query(SideBarCollapsible))
            before = tuple(panel.collapsed for panel in panels)
            self._navigation_changed |= side_bar.restore_navigation()
            self._navigation_changed |= before != tuple(panel.collapsed for panel in panels)
            side_bar.schedule_hydration()
        if sidebar := self.query_one_optional(CommsSidebar):
            sidebar.prepare_navigation()
            self.call_after_first_frame(sidebar, sidebar.start_navigation_hydration)

        if tabs := self.query_one_optional(SessionsTabs):
            await tabs._sync_tabs()

    async def layout_navigation(self) -> None:
        """Measure the complete tree, then position its viewport before painting."""
        from toad.widgets.comms_sidebar import CommsSidebar

        sidebar = self.query_one_optional(CommsSidebar)
        if (self._navigation_applied and not self._navigation_changed
                and self._size == self.app.size and not self._layout_required
                and not self._scroll_required and not self._layout_widgets):
            # Textual's ScreenResume already reflowed this mounted screen.
            # Repeating its full compositor pass on every tab activation is
            # unnecessary when navigation/geometry did not change.
            if sidebar is not None and sidebar._last_snapshot is not None:
                if sidebar.restore_scroll():
                    self._refresh_layout(self.app.size, scroll=True)
            return
        self._refresh_layout(self.app.size)
        if sidebar is not None and sidebar._last_snapshot is not None:
            if sidebar.restore_scroll():
                self._refresh_layout(self.app.size, scroll=True)
        # The native resize handlers and sidebar hydration complete normally
        # after the shell is presented, rather than holding a global paint mask.
        self._layout_required = False
        self._scroll_required = False
        self._dirty_widgets.clear()
        self._navigation_applied = True

    def _on_screen_resume(self, event: ScreenResume) -> None:
        # rules_map is a disposable cache. Re-parsing identical stylesheet
        # sources replaces that dictionary and used to force a full-tree
        # restyle of every aged tab when it was next selected. Detect actual
        # CSS source/theme changes instead; source content and scope are both
        # included, while App's generation covers theme-variable refreshes.
        revision = self._style_revision()
        sources = revision.sources
        # Framework dispatch continues to Screen's handler after this adapter.
        # Layout/paint still run; unchanged trees do not need another CSS walk.
        # Newly mounted nodes already received the current stylesheet. A second
        # full-tree CSS walk on their first activation just delays the spinner.
        previous = self._resume_style
        changed = event.refresh_styles and previous is not None and revision != previous
        partially_refreshed = False
        if changed and previous is not None and replace(previous, sources=sources) == revision:
            targets = self._changed_source_targets(previous.sources, sources)
            if targets is not None:
                self.app.stylesheet.update_nodes(targets, animate=False)
                partially_refreshed = bool(targets)
                changed = False
        event.refresh_styles = changed
        self._resume_styles_changed = changed or partially_refreshed
        self._resume_style = revision

    def _changed_source_targets(
        self,
        previous: tuple[tuple[tuple[str, str], CssSource], ...],
        current: tuple[tuple[tuple[str, str], CssSource], ...],
    ) -> list[DOMNode] | None:
        """Find changed-source targets and their potentially inheriting children.

        Loading another kind of screen registers its scoped CSS globally. That
        alone should not restyle every older transcript. Match through Textual's
        parsed declarations, including old rules so removal is not missed. None
        means source reordering requires the ordinary complete refresh.
        """
        old, new = dict(previous), dict(current)
        if [location for location in old if location in new] != [location for location in new if location in old]:
            return None
        changed = [(location, source) for location, source in previous if new.get(location) != source]
        changed.extend((location, source) for location, source in current if old.get(location) != source)
        if not changed:
            return []

        nodes = list(self.walk_children(with_self=True))
        virtual_nodes = [virtual for node in nodes if isinstance(node, Widget)
                         for virtual in node._get_virtual_dom()]
        nodes.extend(virtual_nodes)
        css_types: set[str] = set()
        for node in [*nodes, *self.ancestors]:
            css_types.update(node._css_type_names)
            if type(node).css_path_nodes is not DOMNode.css_path_nodes:
                for ancestor in node.css_path_nodes:
                    css_types.update(ancestor._css_type_names)

        stylesheet = self.app.stylesheet
        possible_rules: list[RuleSet] = []
        for location, source in changed:
            rules = stylesheet._parse_rules(
                source.content, location, is_default_rules=source.is_defaults,
                tie_breaker=source.tie_breaker, scope=source.scope,
            )
            possible_rules.extend(rule for rule in rules if any(
                all(selector.type is not SelectorType.TYPE or selector.name in css_types
                    for selector in group.selectors) for group in rule.selector_set
            ))
        targets: set[DOMNode] = set()
        for node in nodes:
            component_names = {f".{name}" for name in node._get_component_classes()}
            for rule in possible_rules:
                # Virtual component matching happens inside update_nodes. Keep its
                # owner whenever a changed rule could address a component class.
                if (rule.selector_names & component_names or
                        (rule.selector_names & node._selector_names
                         and any(stylesheet._check_rule(rule, node.css_path_nodes)))):
                    targets.update(node.walk_children(with_self=True))
                    break
        # Preserve ancestor-before-descendant application, as a full CSS update
        # does, rather than applying the selected subtree in set iteration order.
        return [node for node in nodes if node in targets]
