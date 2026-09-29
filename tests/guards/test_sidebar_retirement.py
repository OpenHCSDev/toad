"""Deleted widget custody and hand-maintained panel rosters cannot return."""
import ast
import inspect
from pathlib import Path

from textual.widgets import Static
from toad.screens.main import MainScreen
from toad.widgets.session_thread_panels import SessionPanel
from toad.widgets.session_thread_sidebar import SessionThreadSidebar

ROOT = Path(__file__).resolve().parents[2] / "src/toad/widgets"


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
