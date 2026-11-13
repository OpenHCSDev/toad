"""Thread panels own construction and reader state at their declarations."""
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar
from agent_comms.nominal.declared_family import DeclaredFamily
from textual.widget import Widget
from toad.widgets.comms_sidebar import CoordinationStatus
from toad.plan import PlanItem
from toad.widgets.plan import Plan
from toad.widgets.project_panel import ProjectPanel, RestorableProjectPanel
from toad.widgets.project_tree_intent import NO_TREE_INTENT, TreeIntent
from toad.widgets.side_bar import SideBar, SidebarPanelWidget
from toad.thread_identity import SessionIdentity
from toad.widgets.thread_comms import RelationshipSort, RelationshipTreeState, ThreadCommsSidebar

if TYPE_CHECKING:
    from toad.screens.main import MainScreen
    from toad.widgets.session_thread_sidebar import SessionThreadSidebar


class SessionPanel[W: SidebarPanelWidget](DeclaredFamily, affix="SessionPanel"):
    """Only small reader intent survives; the panel is a view of Core state."""
    collapsed: ClassVar[bool] = False
    flex: ClassVar[bool] = False
    panel_id: ClassVar[str | None] = None

    @abstractmethod
    def make_widget(self, screen: MainScreen) -> W: ...

    def make_header(self) -> Widget | None:
        return None

    def compose_panel(self, screen: MainScreen) -> SideBar.Panel:
        return SideBar.Panel(self.declared_name.title(), self.make_widget(screen),
                             flex=self.flex, collapsed=self.collapsed,
                             id=self.panel_id or f"{self.declared_name}-panel",
                             header_control=self.make_header())

    def capture(self, widget: W) -> None:
        """Stateless projections have no independent state to retain."""


class ThreadSessionPanel(SessionPanel[CoordinationStatus]):
    panel_id = "coordination-panel"

    def make_widget(self, screen: MainScreen) -> CoordinationStatus:
        return CoordinationStatus()


class CommsSessionPanel(SessionPanel[ThreadCommsSidebar]):
    def __init__(self) -> None:
        self.states: dict[SessionIdentity, RelationshipTreeState] = {}

    def make_widget(self, screen: MainScreen) -> ThreadCommsSidebar:
        return ThreadCommsSidebar(states=self.states)

    def make_header(self) -> RelationshipSort:
        return RelationshipSort()


class PlanSessionPanel(SessionPanel[Plan]):
    collapsed = True

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
    collapsed = True
    flex = True

    def __init__(self) -> None:
        self.intent: TreeIntent = NO_TREE_INTENT

    def make_widget(self, screen: MainScreen) -> ProjectPanel:
        screen._project_panel = RestorableProjectPanel(screen.project_path.path, intent=self.intent)
        return screen._project_panel

    def capture(self, widget: ProjectPanel) -> None:
        self.intent = widget.capture_intent()


class ContextSessionPanel(SessionPanel):
    """The last right-sidebar panel; only reader intent survives retirement."""
    def __init__(self):
        self.intents = {}

    def make_widget(self, screen):
        from toad.widgets.context_explorer import ContextExplorer
        return ContextExplorer(intents=self.intents)
