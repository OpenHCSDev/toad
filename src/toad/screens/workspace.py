"""The one native workspace frame; session surfaces never own compositors."""

import asyncio
from contextlib import ExitStack
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
from agent_comms.declared_family import DeclaredFamily
from abc import abstractmethod

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


@dataclass(frozen=True)
class WorkspaceLayoutSnapshot:
    """One native layout's size, style and invalidation proof."""

    mounted: bool
    stack_updates: bool
    size: Size
    layout_pending: bool
    scroll_pending: bool
    widgets: frozenset[Widget]
    style: ViewStyleRevision
    geometry_revision: int

    @classmethod
    def capture(cls, screen, *, include_scroll=True):
        return cls(screen.is_attached, screen.stack_updates, screen._size,
                   screen._layout_required, screen._scroll_required if include_scroll else False,
                   frozenset(screen._layout_widgets), screen._style_revision(), screen._geometry_revision)

    @classmethod
    def ready(cls, screen, size):
        return cls(True, True, size, False, False, frozenset(), screen._style_revision(),
                   screen._geometry_revision)


class WorkspaceLayout(DeclaredFamily, affix="WorkspaceLayout"):
    @abstractmethod
    def reusable(self, screen, size, *, include_scroll=True) -> bool: ...


class PendingWorkspaceLayout(WorkspaceLayout):
    def reusable(self, screen, size, *, include_scroll=True):
        return False


@dataclass(frozen=True)
class MeasuredWorkspaceLayout(WorkspaceLayout):
    proof: WorkspaceLayoutSnapshot

    def reusable(self, screen, size, *, include_scroll=True):
        requested = WorkspaceLayoutSnapshot.ready(screen, size)
        if self.proof != requested:
            return False
        return WorkspaceLayoutSnapshot.capture(screen, include_scroll=include_scroll) == requested


class WorkspaceScreen(SidebarFocusOwner, Screen):
    @property
    def COMMANDS(self):
        return self.app.workspace_sessions.source.commands()

    @property
    def coordination_root(self):
        return self.app.workspace_sessions.source.coordination_root()

    CSS_PATH = ["main.tcss", "comms.tcss"]

    def compose(self):
        from textual.containers import Horizontal, Container
        chrome = self.app.workspace_chrome
        yield chrome.navigation
        with Horizontal(id="workspace-body"):
            yield chrome.channels
            yield Container(id="workspace-session-host")
        yield chrome.footer

    def sidebar_focus_target(self):
        return self.app.workspace_sessions.source.sidebar_focus_target()

    # Keep measured geometry for fast revisits, but do not retain every inactive
    # tab's rendered line/segment graph in the cyclic collector's live heap.
    RETAIN_INACTIVE_PAINT = False

    _resume_style: ViewStyleRevision | None = None
    _navigation_layout: WorkspaceLayout = PendingWorkspaceLayout()
    @cached_property
    def frame_presentation(self):
        from toad.frame_presentation import FramePresentation
        return FramePresentation(self)

    @cached_property
    def viewport_presentation(self):
        from toad.widgets.viewport_body import ViewportPresentation
        return ViewportPresentation(self)

    def on_screen_suspend(self) -> None:
        self.frame_presentation.suspend()
        self.viewport_presentation.suspend()

    def on_screen_resume(self) -> None:
        self.viewport_presentation.request()

    async def _message_loop_exit(self) -> None:
        self.frame_presentation.close()
        await super()._message_loop_exit()

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
        if self.viewport_presentation.has_pending_mutations():
            # The window releases its native mutation lock before requesting
            # the compensated layout. Keep damage/layout intent until then.
            self._update_timer.pause()
            return
        if app._atomic_mode_switch or (self.is_current and app._pending_mode_switch is not None
                and app._pending_mode_switch != self.id):
            # Keep invalidation flags while the selected tree is reconciled,
            # and on busy screens the reader is leaving. layout_navigation owns
            # the transaction's geometry; ordinary timers resume afterward.
            self._update_timer.pause()
            return
        super()._on_timer_update()

    def _prepare_compositor_refresh(self) -> bool:
        return self.viewport_presentation.prepare()

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
                     for target in window.history_geometry_targets())

    def _refresh_layout(self, size: Size | None = None, scroll: bool = False) -> None:
        from toad.widgets.history_anchor import WindowRestoration

        # Keep the last committed geometry: reading virtual_region here can
        # itself rebuild Textual's invalidated map with the new child positions.
        # Only the reader's current scroll/follow intent is refreshed pre-layout.
        tracked = tuple(self.viewport_presentation.anchors)
        anchors = [
            (window, position)
            for window in tracked
            if (position := window.prepare_history_layout()) is not None
        ]
        with ExitStack() as restoration:
            # Only an actual anchor transaction compensates source placement.
            # Native resize/clamping is owned by HistoryWindow._size_updated.
            for window, _position in anchors:
                restoration.enter_context(WindowRestoration.geometry(window))
            if not anchors:
                super()._refresh_layout(size, scroll)
                for window in tracked:
                    window.finish_history_layout()
                return
            # Screen normally paints from inside _refresh_layout. Do not expose
            # prepend/eviction coordinates before compensating for their height.
            with self.app.batch_update():
                super()._refresh_layout(size, scroll)
                changed = False
                for window, position in anchors:
                    changed |= window.restore_history_layout(position)
                if changed:
                    super()._refresh_layout(size, scroll=True)
                for window in tracked:
                    window.finish_history_layout()

    def _screen_resized(self, size: Size) -> None:
        if cast("ToadApp", self.app)._atomic_mode_switch and self.is_mounted:
            # App.switch_mode asks for geometry before the destination's tabs
            # and cached sidebar rows have caught up. The navigation transaction
            # measures their completed tree; retain real resize invalidation.
            self._layout_required |= self._size != size
            return
        if self._navigation_layout.reusable(self, size, include_scroll=False):
            # A resumed mounted tab has already been measured at this width.
            # Textual's full reflow walks all descendants even when only the
            # viewport/visibility needs reconciliation. Keep the full path
            # whenever styles, geometry, or hidden content were invalidated.
            self._refresh_layout(size, scroll=True)
        else:
            super()._screen_resized(size)
            # Textual owns these live invalidation facts. Its completed native
            # layout record, rather than several workspace flags, proves reuse.
            native = WorkspaceLayoutSnapshot.capture(self, include_scroll=False)
            ready = WorkspaceLayoutSnapshot.ready(self, size)
            if replace(native, layout_pending=False) == ready:
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

    async def prepare_navigation(self) -> None:
        from toad.widgets.session_tabs import SessionsTabs

        self.frame_presentation.begin()
        changed = await self.app.selected_session.prepare_navigation()
        changed |= self.app.workspace_chrome.prepare_navigation(self)
        if changed:
            self._navigation_layout = PendingWorkspaceLayout()

        if tabs := self.query_one_optional(SessionsTabs):
            await tabs._sync_tabs()

    async def layout_navigation(self) -> None:
        """Measure the selected source and restore its own sidebar position."""
        roster = self.app.workspace_chrome.channels.roster
        if self._navigation_layout.reusable(self, self.app.size):
            if roster.navigation.restore_scroll():
                self._refresh_layout(self.app.size, scroll=True)
            return
        self._refresh_layout(self.app.size)
        if roster.navigation.restore_scroll():
            self._refresh_layout(self.app.size, scroll=True)
        self._layout_required = False
        self._scroll_required = False
        self._dirty_widgets.clear()
        self._navigation_layout = MeasuredWorkspaceLayout(WorkspaceLayoutSnapshot.ready(self, self.app.size))

    def _on_screen_resume(self, event: ScreenResume) -> None:
        self.frame_presentation.resume()
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
        if changed or partially_refreshed:
            self._navigation_layout = PendingWorkspaceLayout()
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
