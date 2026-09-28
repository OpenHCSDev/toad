"""Thread information is presentation; ACP belongs to the conversation."""

from typing import TYPE_CHECKING
from weakref import ref

from textual.app import ComposeResult

from toad.widgets.comms_sidebar import CoordinationStatus
from toad.widgets.plan import Plan
from toad.widgets.project_panel import ProjectPanel
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, ThreadCommsSidebar

if TYPE_CHECKING:
    from toad.screens.main import MainScreen


class SessionThreadSidebar(SideBar):
    """Build a session's rich panels on first reveal, including executing sessions.

    The inherited hydration/navigation owner handles mounting and reconciliation.
    Hidden sessions hold neither panel widgets nor their subscriptions/tasks.
    Once revealed, the original widgets remain with their session: closing a pane
    cannot discard tree selection, scrolling, or operational conversation state.
    """

    def __init__(self, screen: "MainScreen") -> None:
        self._owner = ref(screen)
        self._plan_entries: list[Plan.Entry] = []
        super().__init__(
            id="thread-sidebar", right=True, hide=True,
            navigation=screen._thread_sidebar_state,
            defer_mount=True, defer_until_reveal=True,
            on_hydrated=self._sync_hydrated,
        )

    def _sync_hydrated(self) -> None:
        screen = self._owner()
        if screen is not None:
            screen._sync_thread_sidebar()
        # A plan may arrive between widget construction and mounting. Consume
        # the current declaration after hydration, not that earlier projection.
        self.update_plan(self._plan_entries)

    def update_plan(self, entries: list[Plan.Entry]) -> None:
        """Consume the latest plan while panels are absent, without buffering events."""
        self._plan_entries = entries
        if entries:
            self.navigation.panels_collapsed["Plan"] = False
        if plan := self.query_one_optional(Plan):
            plan.entries = entries
            if entries:
                self.query_one("#plan-panel", SideBarCollapsible).collapsed = False

    def _compose_panels(self) -> ComposeResult:
        if not self.panels:
            screen = self._owner()
            if screen is None:
                raise ReferenceError("The session sidebar owner has retired")
            # Read current identity and project at hydration, after any ACP
            # coordination updates received while this presentation was absent.
            project = ProjectPanel(screen.project_path)
            screen._project_panel = project
            self.panels.extend((
                self.Panel("Thread", CoordinationStatus(screen._comms_thread),
                           id="coordination-panel"),
                self.Panel("Comms", ThreadCommsSidebar(
                    screen._comms_thread, wire_root=screen._coordination_root, live=True),
                    id="thread-comms-panel", header_control=RelationshipSort()),
                self.Panel("Plan", Plan(self._plan_entries), collapsed=True, id="plan-panel"),
                self.Panel("Project", project, flex=True, collapsed=True),
                self.Panel("Recovery", RecoveryView(
                    screen._comms_thread, wire_root=screen._coordination_root),
                    collapsed=True, id="recovery-panel"),
            ))
        yield from super()._compose_panels()
