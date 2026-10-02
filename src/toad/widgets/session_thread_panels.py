"""Thread panels own construction and reader state at their declarations."""
from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar
from agent_comms.declared_family import DeclaredFamily
from textual.widget import Widget
from toad.widgets.comms_sidebar import CoordinationStatus
from toad.plan import PlanItem
from toad.widgets.plan import Plan
from toad.widgets.project_panel import ProjectPanel, RestorableProjectPanel
from toad.widgets.project_tree_intent import ProjectTreeIntent
from toad.widgets.recovery_view import RecoveryView
from toad.widgets.side_bar import SideBar, SideBarCollapsible
from toad.widgets.thread_comms import RelationshipSort, RelationshipTreeState, ThreadCommsSidebar

if TYPE_CHECKING:
    from toad.screens.main import MainScreen
    from toad.widgets.session_thread_sidebar import SessionThreadSidebar


class SessionPanel[W: Widget](DeclaredFamily, affix="SessionPanel"):
    """Only small reader intent survives; the panel is an admitted projection."""
    collapsed: ClassVar[bool] = False
    flex: ClassVar[bool] = False
    panel_id: ClassVar[str | None] = None

    @abstractmethod
    def make_widget(self, screen: "MainScreen") -> W: ...

    def make_header(self) -> Widget | None:
        return None

    def compose_panel(self, screen: "MainScreen") -> SideBar.Panel:
        return SideBar.Panel(self.declared_name.title(), self.make_widget(screen),
                             flex=self.flex, collapsed=self.collapsed,
                             id=self.panel_id or f"{self.declared_name}-panel",
                             header_control=self.make_header())

    def capture(self, widget: W) -> None:
        """Stateless projections have no independent state to retain."""


class ThreadSessionPanel(SessionPanel[CoordinationStatus]):
    panel_id = "coordination-panel"

    def make_widget(self, screen: "MainScreen") -> CoordinationStatus:
        return CoordinationStatus(screen._comms_thread)


class CommsSessionPanel(SessionPanel[ThreadCommsSidebar]):
    def __init__(self) -> None:
        self.states: dict[tuple[str | None, str], RelationshipTreeState] = {}

    def make_widget(self, screen: "MainScreen") -> ThreadCommsSidebar:
        widget = ThreadCommsSidebar(screen._comms_thread, wire_root=screen.coordination_root, live=True)
        widget._states = self.states
        if selected := widget.view_state.selected:
            widget.selected = selected[1]
        return widget

    def make_header(self) -> RelationshipSort:
        return RelationshipSort()

    def capture(self, widget: ThreadCommsSidebar) -> None:
        for group in widget.groups.values():
            widget.view_state.expanded[group.model.key] = group.expanded
            widget.view_state.scroll[group.model.key] = group.member_container.scroll_y


class PlanSessionPanel(SessionPanel[Plan]):
    collapsed = True

    def __init__(self) -> None:
        self.entries: list[PlanItem] = []

    def make_widget(self, screen: "MainScreen") -> Plan:
        return Plan(self.entries)

    def update(self, sidebar: "SessionThreadSidebar", entries: list[PlanItem]) -> None:
        self.entries = entries
        title = self.declared_name.title()
        if entries:
            sidebar.navigation.panels_collapsed[title] = False
        if plan := sidebar.query_one_optional(Plan):
            plan.entries = entries
            if entries:
                sidebar.query_one(f"#{self.declared_name}-panel", SideBarCollapsible).collapsed = False


class ProjectSessionPanel(SessionPanel[ProjectPanel]):
    collapsed = True
    flex = True

    def __init__(self) -> None:
        self.intent: ProjectTreeIntent | None = None

    def make_widget(self, screen: "MainScreen") -> ProjectPanel:
        screen._project_panel = RestorableProjectPanel(screen.project_path, intent=self.intent)
        return screen._project_panel

    def capture(self, widget: ProjectPanel) -> None:
        if widget.directory_tree is not None:
            self.intent = ProjectTreeIntent.capture(widget.directory_tree)


class RecoverySessionPanel(SessionPanel[RecoveryView]):
    collapsed = True

    def make_widget(self, screen: "MainScreen") -> RecoveryView:
        return RecoveryView(screen._comms_thread, wire_root=screen.coordination_root)


class ContextSessionPanel(SessionPanel):
    """The last right-sidebar panel; only reader intent survives retirement."""
    def __init__(self):
        self.intents = {}

    def make_widget(self, screen):
        from toad.widgets.context_explorer import ContextExplorer, ContextTreeIntent
        key = (screen.coordination_root, screen._comms_thread)
        intent = self.intents.setdefault(key, ContextTreeIntent())
        return ContextExplorer(screen._comms_thread, screen.coordination_root, intent=intent)
