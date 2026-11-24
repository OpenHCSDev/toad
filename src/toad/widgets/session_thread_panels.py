"""Thread panels own construction and reader state at their declarations.

Each concrete `SessionPanel` binds to a toolkit-neutral `ThreadSidebarPanel` member via
`panel_type`. That member (declared in `toad.thread_sidebar_declarations`) owns the panel's
identity — heading, panel id, collapsed and flex defaults — so Qt's `ThreadSettingsPane`
can iterate the same family without pulling Textual in.
"""
from abc import abstractmethod
from typing import TYPE_CHECKING
from agent_comms.nominal.declared_family import DeclaredFamily
from textual.widget import Widget
from toad.thread_sidebar_declarations import (
    CommsSidebarPanel,
    ContextSidebarPanel,
    CoordinationSidebarPanel,
    PlanSidebarPanel,
    ProjectSidebarPanel,
    ThreadSidebarPanelBody,
)
from toad.widgets.comms_sidebar import CoordinationStatus
from toad.plan import PlanItem
from toad.widgets.context_explorer import ContextExplorer
from toad.widgets.plan import Plan
from toad.widgets.project_panel import ProjectPanel, RestorableProjectPanel
from toad.widgets.project_tree_intent import NO_TREE_INTENT, TreeIntent
from toad.widgets.side_bar import SideBar, SidebarPanelWidget
from toad.thread_identity import SessionIdentity
from toad.widgets.thread_comms import RelationshipSort, RelationshipTreeState, ThreadCommsSidebar

if TYPE_CHECKING:
    from toad.screens.main import MainScreen
    from toad.widgets.session_thread_sidebar import SessionThreadSidebar


class SessionPanel[W: SidebarPanelWidget](ThreadSidebarPanelBody, DeclaredFamily, affix="SessionPanel"):
    """Only small reader intent survives; the panel is a view of Core state. Identity
    (heading / panel_id / collapsed / flex) comes from `panel_type` in
    `toad.thread_sidebar_declarations`."""
    @property
    def collapsed(self) -> bool:
        return self.panel_type.collapsed

    @property
    def flex(self) -> bool:
        return self.panel_type.flex

    @property
    def panel_id(self) -> str | None:
        return self.panel_type.panel_id

    @abstractmethod
    def make_widget(self, screen: MainScreen) -> W: ...

    def make_header(self) -> Widget | None:
        return None

    def compose_panel(self, screen: MainScreen) -> SideBar.Panel:
        panel = self.panel_spec()
        return SideBar.Panel(title=panel.title, widget=self.make_widget(screen),
                             flex=panel.flex, collapsed=panel.collapsed, id=panel.id,
                             header_control=self.make_header())

    def capture(self, widget: W) -> None:
        """Stateless projections have no independent state to retain."""


class ThreadDetailsPanel(SessionPanel, declared_name=None):
    """The original thread diagnostics shared by session and DM views."""


class ThreadSessionPanel(ThreadDetailsPanel, SessionPanel[CoordinationStatus]):
    panel_type = CoordinationSidebarPanel

    def make_widget(self, screen: MainScreen) -> CoordinationStatus:
        return CoordinationStatus()


class CommsSessionPanel(ThreadDetailsPanel, SessionPanel[ThreadCommsSidebar]):
    panel_type = CommsSidebarPanel

    def __init__(self) -> None:
        self.states: dict[SessionIdentity, RelationshipTreeState] = {}

    def make_widget(self, screen: MainScreen) -> ThreadCommsSidebar:
        return ThreadCommsSidebar(states=self.states)

    def make_header(self) -> RelationshipSort:
        return RelationshipSort()


class PlanSessionPanel(SessionPanel[Plan]):
    panel_type = PlanSidebarPanel

    def __init__(self) -> None:
        self.entries: list[PlanItem] = []

    def make_widget(self, screen: MainScreen) -> Plan:
        return Plan(self.entries)

    def update(self, sidebar: SessionThreadSidebar, entries: list[PlanItem]) -> None:
        self.entries = entries
        if sidebar.panels_loaded:
            plan = next(panel.widget for owner, panel in zip(sidebar._panel_owners, sidebar.panels)
                        if owner is self)
            plan.entries = entries
            if entries:
                sidebar.reveal_panel(plan)


class ProjectSessionPanel(SessionPanel[ProjectPanel]):
    panel_type = ProjectSidebarPanel

    def __init__(self) -> None:
        self.intent: TreeIntent = NO_TREE_INTENT

    def make_widget(self, screen: MainScreen) -> ProjectPanel:
        screen._project_panel = RestorableProjectPanel(screen.project_path.path, intent=self.intent)
        return screen._project_panel

    def capture(self, widget: ProjectPanel) -> None:
        self.intent = widget.capture_intent()


class ContextSessionPanel(SessionPanel):
    """The last right-sidebar panel; only reader intent survives retirement."""
    panel_type = ContextSidebarPanel

    def __init__(self):
        self.intents = {}

    def make_widget(self, screen):
        return ContextExplorer(intents=self.intents)
