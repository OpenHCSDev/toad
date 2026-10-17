"""The one native workspace frame; session surfaces never own compositors."""

import asyncio
from dataclasses import dataclass, replace
from functools import cached_property
from typing import TYPE_CHECKING

from textual.css.model import RuleSet
from textual.css.stylesheet import CssSource
from textual.binding import Binding
from textual.dom import DOMNode
from textual.events import ScreenResume
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget
from textual.box_model import DEFAULT_LAYER
from toad.widget_view import WidgetView

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


class WorkspaceScreen(WidgetView, SidebarFocusOwner, Screen):
    layer_order = (DEFAULT_LAYER, "comms-sidebar", "_tooltips", "_toastrack")

    BINDINGS = [
        Binding("ctrl+b,f20", "show_sidebar", "Sidebar"),
        Binding("escape", "back_to_bottom", "Back to bottom", priority=True, show=False),
    ]

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
        with Horizontal(id="workspace-body").set_styles(layout=chrome):
            yield chrome.channels
            yield Container(id="workspace-session-host")
        yield chrome.footer

    def sidebar_focus_target(self):
        return self.app.workspace_sessions.source.sidebar_focus_target()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_sidebar":
            sidebar = self.app.workspace_chrome.channels
            return sidebar.display and not sidebar.has_focus_within
        if action == "back_to_bottom":
            return self.back_to_bottom_window is not None
        return super().check_action(action, parameters)

    @property
    def back_to_bottom_window(self):
        published = self._compositor.published_widgets
        return next((window for window in self.history_windows
                     if window in published and window.can_jump_to_latest), None)

    def action_back_to_bottom(self) -> None:
        if (window := self.back_to_bottom_window) is not None:
            window.jump_to_latest()

    def action_show_sidebar(self) -> None:
        sidebar = self.app.workspace_chrome.channels
        sidebar.reveal()
        if title := sidebar.query_one_optional("SideBarCollapsible CollapsibleTitle"):
            title.focus()

    # Keep measured geometry for fast revisits, but do not retain every inactive
    # tab's rendered line/segment graph in the cyclic collector's live heap.

    _resume_style: ViewStyleRevision | None = None
    _navigation_layout: WorkspaceLayout = PendingWorkspaceLayout()
    @cached_property
    def frame_presentation(self):
        from toad.frame_presentation import FramePresentation
        return FramePresentation(self)

    @cached_property
    def history_windows(self) -> set:
        """Mounted history windows; each registers itself for its lifetime."""
        return set()

    def _layout_geometry_targets(self) -> tuple[Widget, ...]:
        # Reader positions and restorations compensate against these widgets,
        # so viewport layout places them even when they are off screen.
        return tuple(target for window in self.history_windows
                     for target in window.history_geometry_targets())

    def on_screen_suspend(self) -> None:
        self.frame_presentation.suspend()
        for window in tuple(self.history_windows):
            window.retire_presentation_wait()

    def on_screen_resume(self) -> None:
        for window in tuple(self.history_windows):
            window.request_preparation()

    async def _message_loop_exit(self) -> None:
        self.frame_presentation.close()
        await super()._message_loop_exit()

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

    def _on_frame_published(self) -> None:
        super()._on_frame_published()
        if self is self.app.screen:
            self.frame_presentation.displayed()

    def release_frame_callback(self, owner, callback) -> bool:
        """Inactive native scenes retain their work for their next frame."""
        if not self.is_current:
            return False
        return self.app.workspace_sessions.release_frame_callback(owner, callback)

    def _use_viewport_layout(self) -> bool:
        return self.is_current

    def _layout_steps(self, size: Size | None = None, scroll: bool = False, deadline=None):
        changes = tuple((change, change.layout_requests) for window in self.history_windows
                        if (change := window.history_change) is not None)
        # Each window that keeps a reader position is put back on it by this
        # layout. Only the kept position is read before layout: reading
        # virtual_region here can itself rebuild Textual's invalidated map.
        kept = tuple(window for window in self.history_windows if window.reader_for_layout() is not None)
        if not kept:
            # Resize and clamping alone are handled by HistoryWindow._size_updated.
            yield from super()._layout_steps(size, scroll, deadline)
        else:
            # Screen normally paints from inside _refresh_layout. Do not show
            # rows added or removed above the reader before the window has
            # scrolled by their height.
            with self.app.batch_update():
                yield from super()._layout_steps(size, scroll, deadline)
                if any([window.place_reader() for window in kept]):
                    yield from super()._layout_steps(size, scroll=True)
        for change, answered in changes:
            change.finish_layout(answered)

    def reader_kept(self) -> None:
        """A history window just kept its reader, for a change about to be made.

        A layout paused between its steps started without that position: it
        would arrange the change and show it before the reader is put back.
        The next layout replaces it and takes the requests it had not finished.
        """
        steps = self._stepped_layout
        if steps is not None and not steps.gi_running:
            self._stop_stepped_layout()
            self._layout_required = True
            self.check_idle()

    def _screen_resized(self, size: Size) -> None:
        if size != self._size:
            # Rows above the reader wrap differently at the new width.
            for window in self.history_windows:
                window.keep_reader()
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
        changed |= await self.app.workspace_chrome.prepare_navigation(self)
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
        # The frames are held: the layout runs over loop turns so input is
        # handled between its steps, and is published once, at its end.
        await self.layout_in_steps(self.app.size)
        if roster.navigation.restore_scroll():
            self._refresh_layout(self.app.size, scroll=True)
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
        stylesheet = self.app.stylesheet
        possible_rules: list[RuleSet] = []
        for location, source in changed:
            rules = stylesheet._parse_rules(
                source.content, location, is_default_rules=source.is_defaults,
                tie_breaker=source.tie_breaker, scope=source.scope,
            )
            possible_rules.extend(rules)
        targets: set[DOMNode] = set()
        for node in nodes:
            component_names = {f".{name}" for name in node._get_component_classes()}
            for rule in possible_rules:
                # Virtual component matching happens inside update_nodes. Keep its
                # owner whenever a changed rule could address a component class.
                if (rule.selector_names & component_names or
                        (rule.selector_names & node._selector_names
                         and any(rule.check(node)))):
                    targets.update(node.walk_children(with_self=True))
                    break
        # Preserve ancestor-before-descendant application, as a full CSS update
        # does, rather than applying the selected subtree in set iteration order.
        return [node for node in nodes if node in targets]
