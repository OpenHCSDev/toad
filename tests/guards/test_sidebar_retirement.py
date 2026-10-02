"""Deleted widget custody and hand-maintained panel rosters cannot return."""
import ast
import inspect
from pathlib import Path

from textual.widgets import Static
from toad.screens.main import MainScreen
from toad.widgets.session_thread_panels import SessionPanel
from toad.widgets.session_thread_sidebar import SessionThreadSidebar

ROOT = Path(__file__).resolve().parents[2] / "src/toad/widgets"


def test_member_source_updates_share_disclosure_custody():
    from toad.widgets.comms_sidebar import ChannelGroup
    from toad.widgets.sidebar_tree import SidebarGroup
    from toad.widgets.thread_comms import RelationshipRows

    assert RelationshipRows._sync_members is SidebarGroup._sync_members
    function = ast.parse(inspect.getsource(RelationshipRows).strip())
    update = next(node for node in function.body[0].body
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == 'update_group')
    assert len(update.body) == 1 and isinstance(update.body[0], ast.AsyncWith)
    assert ast.unparse(update.body[0].items[0].context_expr) == 'self.member_lock'

    channel = ast.parse(inspect.getsource(ChannelGroup).strip())
    methods = {node.name: node for node in channel.body[0].body
               if isinstance(node, ast.AsyncFunctionDef)}
    assert 'update_members' not in methods
    assert any(isinstance(node, ast.AsyncWith)
               and ast.unparse(node.items[0].context_expr).endswith('.projection.lock')
               for node in ast.walk(methods['_sync_members']))
    for method in ('_sync_members', 'present'):
        assert any(isinstance(node, ast.Await)
                   and ast.unparse(node.value) == 'super()._sync_members()'
                   for node in ast.walk(methods[method]))
    assert not {'_view', '_snapshot', '_unread', '_channel_active', '_lock', '_sync_lock'} & {
        node.attr for node in ast.walk(channel) if isinstance(node, ast.Attribute)
    }


def test_channel_row_order_has_no_stored_copy():
    for path in ROOT.parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                assert node.attr != "member_rows", (path, node.lineno)


def test_new_panel_case_is_derived_and_owns_its_presentation():
    assert inspect.isabstract(SessionPanel)

    class AcceptanceSessionPanel(SessionPanel[Static]):
        def make_widget(self, screen):
            return Static("New case renders through its declaration")

    assert AcceptanceSessionPanel in SessionPanel.members_with(SessionPanel)
    screen = MainScreen(Path("."))
    sidebar = SessionThreadSidebar(screen)
    owner = next(owner for owner in sidebar._panel_owners if isinstance(owner, AcceptanceSessionPanel))
    assert owner.compose_panel(screen).title == "Acceptance"


def test_panel_roster_and_old_retained_plan_authority_are_deleted():
    tree = ast.parse((ROOT / "session_thread_sidebar.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"_plan_entries", "PLAN_TITLE"}
        if isinstance(node, ast.Call):
            assert not (isinstance(node.func, ast.Attribute) and node.func.attr == "Panel")
            assert not (isinstance(node.func, ast.Attribute) and node.func.attr == "create_task")
    assert not (ROOT.parents[2] / "tests/session_thread_panels_pilot.py").exists()
    assert not (ROOT.parents[2] / "tests/many_tabs_sidebar_observation_pilot.py").exists()


def test_project_admission_does_not_depend_on_a_stale_painted_frame():
    tree = ast.parse((ROOT / "project_panel.py").read_text())
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_ensure_tree")
    assert not any(isinstance(node, ast.Attribute) and node.attr == "is_on_screen"
                   for node in ast.walk(method))
