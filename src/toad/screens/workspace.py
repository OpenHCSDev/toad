"""The one native workspace frame; session surfaces never own compositors."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, replace
from functools import cached_property

from agent_comms.declared_family import DeclaredFamily
from textual.binding import Binding, BindingsMap
from textual.box_model import DEFAULT_LAYER
from textual.events import ScreenResume
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget

from toad.app_node import ToadNode
from toad.widget_view import WidgetView
from toad.widget_actions import ProfileKeys


@dataclass(frozen=True)
class WorkspaceLayoutSnapshot:
    """One native layout's size, style and invalidation proof."""

    mounted: bool
    stack_updates: bool
    size: Size
    layout_pending: bool
    scroll_pending: bool
    widgets: frozenset[Widget]
    geometry_revision: int

    @classmethod
    def capture(cls, screen, *, include_scroll=True):
        return cls(
            screen.is_attached,
            screen.stack_updates,
            screen._size,
            screen._layout_required,
            screen._scroll_required if include_scroll else False,
            frozenset(screen._layout_widgets),
            screen._geometry_revision,
        )

    @classmethod
    def ready(cls, screen, size):
        return cls(
            True, True, size, False, False, frozenset(), screen._geometry_revision
        )


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
        return (
            WorkspaceLayoutSnapshot.capture(screen, include_scroll=include_scroll)
            == requested
        )


class WorkspaceScreen(ProfileKeys, WidgetView, ToadNode, Screen):
    layer_order = (DEFAULT_LAYER, "comms-sidebar", "_tooltips", "_toastrack")

    BINDINGS = [
        Binding("ctrl+b,f20", "show_sidebar", "Sidebar"),
        Binding(
            "escape", "back_to_bottom", "Back to bottom", priority=True, show=False
        ),
    ]

    @classmethod
    def require(cls, screen: Screen) -> "WorkspaceScreen":
        """Resolve the native widget screen at the workspace boundary."""
        if not isinstance(screen, cls):
            raise TypeError(f"{type(screen).__name__} is not a {cls.__name__}")
        return screen

    @property
    def COMMANDS(self):
        return self.app.workspace_sessions.source.commands()

    @property
    def coordination_root(self):
        return self.app.workspace_sessions.source.coordination_root()

    CSS_PATH = ["main.tcss", "comms.tcss"]

    def compose(self):
        from textual.containers import Container, Horizontal

        chrome = self.app.workspace_chrome
        yield chrome.navigation
        with Horizontal(id="workspace-body").set_styles(layout=chrome):
            yield chrome.channels
            yield Container(id="workspace-session-host")
        yield chrome.footer

    def binding_scopes(self):
        return tuple(
            (node, BindingsMap(scoped for binding in node.declared_bindings()
                               for scoped in binding.fallback_bindings()))
            for node in self.app.selected_session.keyboard_scopes()
        )

    def belongs_to_wire(self, root) -> bool:
        """Shared workspace chrome follows the observed wire, not a retained tab."""
        return True

    def start_sidebar_navigation(self, sidebar) -> None:
        self.frame_presentation.defer(sidebar, sidebar.navigation.start)

    def focus_sidebar_return(self) -> None:
        self.app.workspace_sessions.source.focus_sidebar_return()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "show_sidebar":
            sidebar = self.app.workspace_chrome.channels
            return sidebar.display and not sidebar.has_focus_within
        if action == "back_to_bottom":
            return (
                not (self.focused is not None and self.focused.uses_screen_coordinates)
                and self.back_to_bottom_window is not None
            )
        return super().check_action(action, parameters)

    @property
    def back_to_bottom_window(self):
        published = self._compositor.published_widgets
        return next(
            (
                window
                for window in self.history_windows
                if window in published and window.can_jump_to_latest
            ),
            None,
        )

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
        return tuple(
            target
            for window in self.history_windows
            for target in window.history_geometry_targets()
        )

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

    def _layout_steps(
        self, size: Size | None = None, scroll: bool = False, deadline=None
    ):
        changes = tuple(
            (change, change.layout_requests)
            for window in self.history_windows
            if (change := window.history_change) is not None
        )
        # Capture the old rows before any descendant measures its new width;
        # that layout and reader placement belong to one unpublished frame.
        with self.app.batch_update():
            for window in self.history_windows:
                if window.shown:
                    window.keep_reader()
            yield from super()._layout_steps(size, scroll, deadline)
            if any(
                [
                    window.place_reader()
                    for window in self.history_windows
                    if window.reader_for_layout() is not None
                ]
            ):
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
            not widget.is_attached
            or (offset is not None and not isinstance(widget.parent, Widget))
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
        self._navigation_layout = MeasuredWorkspaceLayout(
            WorkspaceLayoutSnapshot.ready(self, self.app.size)
        )

    def _on_screen_resume(self, event: ScreenResume) -> None:
        self.frame_presentation.resume()
        # Native Screen resume updates changed stylesheet sources.
